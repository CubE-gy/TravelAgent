"""Produce a grounded Chinese reply after constrained travel tools run."""

import json

from pydantic import BaseModel, Field

from app.services.llm_provider import LlmMessage, LlmMessageRole, LlmProvider, LlmProviderError
from app.services.trip_state_update_service import TripStateUpdateResult
from app.schemas.trip_state_clarification import TripStateClarification


class AgentFinalReply(BaseModel):
    """The only user-facing wording emitted after tool execution."""

    message: str = Field(min_length=1, max_length=2000)


FINAL_REPLY_INSTRUCTIONS = """Write one concise Chinese reply for a travel-planning Agent.
Use only the supplied tool results. State what was actually saved or confirmed, mention
map lookup failures without inventing facts, and include any supplied clarification
question naturally. Do not claim a place is on the map unless its resolution status is
resolved. Do not expose JSON, internal tool names, revisions, or database details."""


class TripAgentReplyService:
    """Turn persisted tool facts into one grounded final Agent reply."""

    def __init__(self, provider: LlmProvider) -> None:
        self._provider = provider

    def generate(
        self,
        update_result: TripStateUpdateResult,
        clarification: TripStateClarification | None = None,
    ) -> str:
        facts = {
            "state": update_result.state.model_dump(mode="json"),
            "location_failures": [failure.__dict__ for failure in update_result.location_failures],
            "clarification": (
                clarification.model_dump(mode="json")
                if clarification is not None
                else {"questions": []}
            ),
        }
        try:
            reply = self._provider.generate_structured(
                [
                    LlmMessage(role=LlmMessageRole.SYSTEM, content=FINAL_REPLY_INSTRUCTIONS),
                    LlmMessage(
                        role=LlmMessageRole.USER,
                        content="Executed travel tool results JSON:\n"
                        + json.dumps(facts, ensure_ascii=False, separators=(",", ":")),
                    ),
                ],
                AgentFinalReply,
            )
            return reply.message
        except LlmProviderError:
            return "已处理本次旅行信息。你可以继续补充地点、酒店、交通或偏好。"
