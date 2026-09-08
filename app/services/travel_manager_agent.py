"""The single Stage 4 travel Agent and its bounded tool-turn protocol."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.schemas.trip_state import TripState
from app.services.llm_provider import LlmProviderError, LlmResponseError
from app.services.travel_tool import ToolContext, ToolObservation, TravelTool
from app.services.travel_tool_registry import TravelToolRegistry
from app.services.trip_agent_reply_service import TripAgentReplyService
from app.services.trip_state_extraction_service import (
    AgentDecision,
    TripStateMessageIntent,
)
from app.services.trip_state_update_service import TripStateUpdateResult


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
        return self.tool is not None

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
        turn_facts: list[dict[str, object]] | None = None,
        recommendation_context: dict[str, object] | None = None,
    ) -> AgentDecision: ...


class TravelManagerAgent:
    """Choose bounded tools, then turn their verified facts into the final reply.

    The model never receives a database session, map client, or arbitrary callable.
    It can only return the strictly validated decision schema consumed by the tool
    conversation service. The current workflow executes one tool batch followed
    by a reply; it does not implement an autonomous multi-round tool loop.
    """

    def __init__(
        self,
        planner: TravelManagerPlanner,
        reply_generator: TripAgentReplyService,
        tool_registry: TravelToolRegistry,
    ) -> None:
        self._planner = planner
        self._reply_generator = reply_generator
        self._tool_registry = tool_registry

    def decide(
        self,
        current_state: TripState,
        user_message: str,
        *,
        trip_memories: list[dict[str, object]],
        conversation_context: list[dict[str, str]] | None = None,
        turn_facts: list[dict[str, object]] | None = None,
        recommendation_context: dict[str, object] | None = None,
    ) -> TravelManagerTurn:
        """Return a direct answer or a batch of allow-listed travel operations."""
        try:
            planner_args: dict[str, object] = {
                "conversation_context": conversation_context,
                "turn_facts": turn_facts,
            }
            if recommendation_context is not None:
                planner_args["recommendation_context"] = recommendation_context
            decision = self._planner.extract(
                current_state, user_message, trip_memories,
                **planner_args,
            )
        except LlmResponseError:
            decision = AgentDecision(
                intent=TripStateMessageIntent.CONVERSATION,
                assistant_message="我暂时未能理解这条消息，本次没有修改行程。请换一种说法或稍后重试。",
            )
        return TravelManagerTurn(decision)

    @staticmethod
    def direct_reply(turn: TravelManagerTurn, state: TripState) -> str:
        """Return a validated direct answer without invoking any tool."""
        return turn.decision.assistant_message or "请再说明一下这次希望我帮你做什么，本次没有修改行程。"

    def run_tool(self, turn: TravelManagerTurn, context: ToolContext) -> ToolObservation:
        """Dispatch the turn's tool through the registry, returning its observation."""
        if turn.tool is None:
            raise ValueError("turn has no tool to run")
        tool: TravelTool = self._tool_registry.get(turn.tool.value)
        args = tool.extract_args(turn.decision)
        return tool.run(args, context)

    def reply_after_tools(
        self,
        observation: ToolObservation,
        *,
        current_state: TripState,
        user_message: str | None = None,
        conversation_context: list[dict[str, str]] | None = None,
        turn_facts: list[dict[str, object]] | None = None,
        clarification=None,
    ) -> str:
        """Ask the same Agent to word only the facts produced by its tool."""
        return self._reply_generator.generate(
            observation, current_state=current_state, user_message=user_message,
            conversation_context=conversation_context, turn_facts=turn_facts,
            clarification=clarification,
        )
