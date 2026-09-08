"""Produce a grounded Chinese reply after constrained travel tools run."""

from pydantic import BaseModel, Field

from app.services.llm_provider import LlmProvider, LlmProviderError
from app.services.agent_context_builder import build_agent_messages
from app.services.travel_tool import ToolObservation
from app.schemas.trip_state import TripState
from app.schemas.trip_state_clarification import TripStateClarification


class AgentFinalReply(BaseModel):
    """The only user-facing wording emitted after tool execution."""

    message: str = Field(min_length=1, max_length=2000)


FINAL_REPLY_INSTRUCTIONS = """Write one concise Chinese reply for a travel-planning Agent.
Use only the supplied tool outcome and location lookup facts. State what was actually
saved or confirmed, describe the search candidates in plain language (names, addresses,
categories; do not invent prices or distances) and mention any map lookup failures
without inventing facts. Do not claim a place is on the map unless its resolution status
is resolved. Do not expose JSON, internal tool names, revisions, or database details."""


class TripAgentReplyService:
    """Turn a tool's verified outcome into one grounded final Agent reply."""

    def __init__(self, provider: LlmProvider) -> None:
        self._provider = provider

    def generate(
        self,
        tool_observation: ToolObservation | None,
        *,
        current_state: TripState,
        user_message: str | None = None,
        conversation_context: list[dict[str, str]] | None = None,
        turn_facts: list[dict[str, object]] | None = None,
        clarification: TripStateClarification | None = None,
    ) -> str:
        facts = {
            "tool_name": tool_observation.summary if tool_observation else None,
            "tool_outcome": tool_observation.data if tool_observation else {},
            "clarification": (
                clarification.model_dump(mode="json")
                if clarification is not None
                else {"questions": []}
            ),
        }
        try:
            reply = self._provider.generate_structured(
                build_agent_messages(
                    FINAL_REPLY_INSTRUCTIONS, current_state,
                    user_message or "请根据本次执行结果回复。",
                    history=conversation_context, turn_facts=turn_facts,
                    tool_result=facts,
                ),
                AgentFinalReply,
            )
            return reply.message
        except LlmProviderError:
            if tool_observation is not None:
                if tool_observation.data.get("location_failures"):
                    return "已保留本次旅行信息，但部分地点查询失败，尚未确认地图位置。请稍后重试。"
                if tool_observation.summary.startswith("search_recommendations"):
                    candidates = tool_observation.data.get("candidates") or []
                    if candidates:
                        names = "、".join(candidate["name"] for candidate in candidates[:3])
                        return f"我找到了 {len(candidates)} 个附近候选，先看看：{names}。请在下方卡片中点选。"
                    return "本次没有在目的地附近找到可确认的候选。"
            return "已处理本次旅行信息。你可以继续补充地点、酒店、交通或偏好。"
