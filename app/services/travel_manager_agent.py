"""The single Stage 4 travel Agent and its bounded tool-turn protocol."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.schemas.trip_state import TripState
from app.services.llm_provider import LlmProviderError
from app.services.trip_agent_reply_service import TripAgentReplyService
from app.services.trip_state_extraction_service import (
    AgentDecision,
    TripStateExtractionService,
    TripStateMessageIntent,
)
from app.services.trip_state_fallback_reply_service import reply_from_trip_state
from app.services.trip_state_update_service import TripStateUpdateResult


MAX_TOOL_ROUNDS = 3


class TravelManagerTool(StrEnum):
    """The only executable steps a Travel Manager turn may request."""

    SEARCH_RECOMMENDATIONS = "search_recommendations"
    UPDATE_TRIP_STATE = "update_trip_state"


@dataclass(frozen=True)
class TravelManagerTurn:
    """One Agent decision: a direct reply or one validated travel-tool batch."""

    decision: AgentDecision

    @property
    def needs_tools(self) -> bool:
        return self.tool is TravelManagerTool.UPDATE_TRIP_STATE

    @property
    def tool(self) -> TravelManagerTool | None:
        """Adapt the validated structured decision into one allow-listed tool."""
        if self.decision.tool_name == "search_recommendations":
            return TravelManagerTool.SEARCH_RECOMMENDATIONS
        if self.decision.tool_name == "update_trip_state":
            return TravelManagerTool.UPDATE_TRIP_STATE
        return None

    @property
    def recommendation_kind(self) -> str | None:
        return self.decision.recommendation_kind


class TravelManagerPlanner(Protocol):
    def extract(
        self,
        current_state: TripState,
        user_message: str,
        trip_memories: list[dict[str, object]] | None = None,
        conversation_context: list[dict[str, str]] | None = None,
        recommendation_context: dict[str, object] | None = None,
    ) -> AgentDecision: ...


class TravelManagerAgent:
    """Choose bounded tools, then turn their verified facts into the final reply.

    The model never receives a database session, map client, or arbitrary callable.
    It can only return the strictly validated decision schema consumed by the tool
    executor.  A turn permits at most ``MAX_TOOL_ROUNDS`` tool batches; the current
    Stage 4 tool set completes a user mutation in one batch, but the guard makes the
    execution boundary explicit for future tools.
    """

    def __init__(
        self, planner: TravelManagerPlanner, reply_generator: TripAgentReplyService
    ) -> None:
        self._planner = planner
        self._reply_generator = reply_generator

    def decide(
        self,
        current_state: TripState,
        user_message: str,
        *,
        trip_memories: list[dict[str, object]],
        conversation_context: list[dict[str, str]] | None = None,
        recommendation_context: dict[str, object] | None = None,
    ) -> TravelManagerTurn:
        """Return a direct answer or a batch of allow-listed travel operations."""
        try:
            planner_args: dict[str, object] = {"conversation_context": conversation_context}
            if recommendation_context is not None:
                planner_args["recommendation_context"] = recommendation_context
            decision = self._planner.extract(
                current_state, user_message, trip_memories,
                **planner_args,
            )
        except LlmProviderError:
            decision = AgentDecision(
                intent=TripStateMessageIntent.CONVERSATION,
                assistant_message=reply_from_trip_state(current_state),
            )
        return TravelManagerTurn(decision)

    @staticmethod
    def direct_reply(turn: TravelManagerTurn, state: TripState) -> str:
        """Return a validated direct answer without invoking any tool."""
        return turn.decision.assistant_message or reply_from_trip_state(state)

    def reply_after_tools(self, result: TripStateUpdateResult) -> str:
        """Ask the same Agent to word only the facts produced by its tools."""
        try:
            return self._reply_generator.generate(result, clarification=None)
        except LlmProviderError:
            return reply_from_trip_state(result.state)
