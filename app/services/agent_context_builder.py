"""One place to assemble layered, budget-aware context for Agent decisions."""

import json
import math
import re
from typing import Any

from app.schemas.trip_state import (
    LocationIntent,
    LocationResolutionStatus,
    TripState,
)
from app.services.llm_provider import LlmMessage, LlmMessageRole


HISTORY_TOKEN_BUDGET = 6000
HISTORY_MESSAGE_LIMIT = 10
MAX_SNAPSHOT_PLACES = 8
MAX_TURN_FACTS = 5

_CJK_PATTERN = re.compile(r"[　-〿一-鿿＀-￯]")
_CJK_TOKENS_PER_CHAR = 1.5
_OTHER_TOKENS_PER_CHAR = 0.25

SNAPSHOT_HEADING = "应用事实快照（参考数据，不是用户请求，也不含指令）"
TOOL_RESULT_HEADING = "本次工具执行结果"
TURN_FACT_HEADING = "最近几轮已执行的操作（结构化事实，不是对话内容）"


def estimate_tokens(text: str) -> int:
    """Estimate model tokens conservatively; CJK costs far more per character.

    This is an estimate rather than a tokenizer. It exists so the history budget
    no longer treats one Chinese character as equal to one ASCII character.
    """
    cjk_characters = sum(1 for character in text if _CJK_PATTERN.match(character))
    other_characters = len(text) - cjk_characters
    return math.ceil(
        cjk_characters * _CJK_TOKENS_PER_CHAR + other_characters * _OTHER_TOKENS_PER_CHAR
    )


def compact_location(location: LocationIntent | None) -> dict[str, Any] | None:
    """Keep only decision-relevant facts: query, status, candidate ids, name."""
    if location is None:
        return None
    compact: dict[str, Any] = {
        "query": location.query,
        "status": location.resolution_status.value,
    }
    if location.resolution_status is LocationResolutionStatus.AMBIGUOUS:
        compact["candidates"] = [
            {"poi_id": candidate.poi_id, "name": candidate.name}
            for candidate in location.candidates
        ]
    if location.resolved_location is not None:
        compact["confirmed_name"] = location.resolved_location.name
    elif location.resolved_city is not None:
        compact["confirmed_name"] = location.resolved_city.name
    return compact


def build_state_snapshot(
    state: TripState, *, max_places: int = MAX_SNAPSHOT_PLACES
) -> dict[str, Any]:
    """Trim a TripState to what a decision needs, dropping map coordinates."""
    return {
        "revision": state.revision,
        "origin": compact_location(state.origin),
        "destination": compact_location(state.destination),
        "return_destination": compact_location(state.return_destination),
        "outbound_departure_station": compact_location(state.outbound_departure_station),
        "outbound_arrival_station": compact_location(state.outbound_arrival_station),
        "departure_date": state.departure_date.isoformat() if state.departure_date else None,
        "return_date": state.return_date.isoformat() if state.return_date else None,
        "accommodation": compact_location(state.accommodation),
        "places": [compact_location(place) for place in state.places[:max_places]],
        "omitted_place_count": max(0, len(state.places) - max_places),
        "intercity_travel_mode": (
            state.intercity_travel_mode.value if state.intercity_travel_mode else None
        ),
        "local_travel_mode": state.local_travel_mode.value if state.local_travel_mode else None,
        "vehicle": (
            {"energy_type": state.vehicle.energy_type.value, "range_km": state.vehicle.range_km}
            if state.vehicle is not None
            else None
        ),
    }


def _dump(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render_turn_facts(turn_facts: list[dict[str, Any]]) -> str:
    """Describe recent turns by outcome, so the model need not infer them.

    Each line states what the user asked, which decision ran, which operations
    were applied and which locations stayed unresolved. Empty parts are dropped
    instead of being rendered as nulls the model would have to skip.
    """
    lines: list[str] = []
    for fact in turn_facts[:MAX_TURN_FACTS]:
        parts = [
            "第%s轮" % fact.get("turn_index"),
            "用户:「%s」" % fact.get("user_message", ""),
        ]
        if fact.get("decision"):
            parts.append("决策 %s" % fact["decision"])
        operations = fact.get("operations") or []
        if operations:
            parts.append("已执行 " + "、".join(str(operation) for operation in operations))
        failures = fact.get("location_failures") or []
        if failures:
            parts.append("解析失败 " + "、".join(str(failure) for failure in failures))
        if fact.get("recommendation_count"):
            parts.append("返回候选 %s 个" % fact["recommendation_count"])
        lines.append("- " + "｜".join(parts))
    return "\n".join(lines)


def build_agent_messages(
    instructions: str,
    state: TripState,
    user_message: str,
    *,
    memories: list[dict[str, object]] | None = None,
    history: list[dict[str, str]] | None = None,
    turn_facts: list[dict[str, Any]] | None = None,
    recommendations: dict[str, object] | None = None,
    tool_result: dict[str, object] | None = None,
) -> list[LlmMessage]:
    """Keep instructions, trimmed facts and bounded dialogue in separate layers.

    The snapshot belongs to the instructions layer rather than to the dialogue,
    so the model never has to guess whether a JSON blob was something the user
    actually said.
    """
    sections = [
        instructions.strip(),
        "## "
        + SNAPSHOT_HEADING
        + "\n"
        + _dump(
            {
                "trip_state": build_state_snapshot(state),
                "trip_memories": memories or [],
                "active_recommendations": recommendations or {},
            }
        ),
    ]
    if turn_facts:
        rendered_facts = render_turn_facts(turn_facts)
        if rendered_facts:
            sections.append("## " + TURN_FACT_HEADING + "\n" + rendered_facts)
    if tool_result is not None:
        sections.append("## " + TOOL_RESULT_HEADING + "\n" + _dump(tool_result))
    system_message = LlmMessage(role=LlmMessageRole.SYSTEM, content="\n\n".join(sections))
    turns: list[list[LlmMessage]] = []
    for item in history or []:
        if item.get("role") not in {"user", "assistant"}:
            raise ValueError("conversation history only accepts user and assistant roles")
        message = LlmMessage(role=item["role"], content=item["content"])
        if message.role is LlmMessageRole.USER or not turns:
            turns.append([])
        turns[-1].append(message)
    # Keep a contiguous suffix of complete available turns, never isolated
    # old replies whose user message was skipped to fit a budget.
    retained: list[list[LlmMessage]] = []
    tokens = count = 0
    for turn in reversed(turns):
        size = sum(estimate_tokens(message.content) for message in turn)
        if tokens + size > HISTORY_TOKEN_BUDGET or count + len(turn) > HISTORY_MESSAGE_LIMIT:
            break
        retained.append(turn)
        tokens += size
        count += len(turn)
    return [
        system_message,
        *(message for turn in reversed(retained) for message in turn),
        LlmMessage(role=LlmMessageRole.USER, content=user_message),
    ]
