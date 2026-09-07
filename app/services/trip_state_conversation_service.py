"""Unified Stage 2 conversational handling for one Trip."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.schemas.trip_state import TripState
from app.schemas.trip_state_assessment import TripStateAssessment
from app.schemas.trip_state_clarification import TripStateClarification
from app.services.trip_state_location_resolution_service import LocationResolutionFailure
from app.services.trip_state_update_service import TripStateUpdateResult
from app.services.llm_provider import LlmProviderError
from app.services.travel_manager_agent import TravelManagerAgent, TravelManagerTool
from app.services.trip_state_assessor import assess_trip_state
from app.schemas.trip_recommendation import TripRecommendationContext, TripRecommendationRead
from app.services.trip_recommendation_service import TripRecommendationService
from app.repositories.trip_recommendation_session import get_active_recommendation_session


class TripStateUpdater(Protocol):
    """The state-update capability needed by the conversation service."""

    def update(
        self,
        session: Session,
        trip_id: UUID,
        user_message: str,
        *,
        expected_revision: int,
        commit: bool = True,
    ) -> TripStateUpdateResult: ...


class TripStateClarifier(Protocol):
    """The clarification capability needed after a state update."""

    def generate(self, update_result: TripStateUpdateResult) -> TripStateClarification: ...


class TripAgentReplyGenerator(Protocol):
    """Writes the grounded reply after one or more travel tools executed."""

    def generate(
        self, update_result: TripStateUpdateResult, clarification: TripStateClarification
    ) -> str: ...


@dataclass(frozen=True)
class TripStateConversationResult:
    """The complete result of handling one user message for one Trip."""

    state: TripState
    location_failures: list[LocationResolutionFailure]
    assessment: TripStateAssessment
    clarification: TripStateClarification
    assistant_message: str | None = None
    recommendations: list[TripRecommendationRead] | None = None
    recommendation_session_id: UUID | None = None


class TripStateConversationService:
    """Coordinate state updating and necessary clarification generation."""

    def __init__(
        self,
        updater: TripStateUpdater,
        clarifier: TripStateClarifier,
        reply_generator: TripAgentReplyGenerator | None = None,
        manager_agent: TravelManagerAgent | None = None,
        recommendation_service: TripRecommendationService | None = None,
    ) -> None:
        self._updater = updater
        self._clarifier = clarifier
        self._reply_generator = reply_generator
        self._manager_agent = manager_agent
        self._recommendation_service = recommendation_service

    def handle(
        self,
        session: Session,
        trip_id: UUID,
        user_message: str,
        *,
        expected_revision: int,
        commit: bool = True,
        conversation_context: list[dict[str, str]] | None = None,
        recommendation_context: TripRecommendationContext | None = None,
    ) -> TripStateConversationResult:
        """Let the single Travel Manager Agent answer or invoke bounded tools."""
        try:
            if self._manager_agent is not None:
                current_state = self._updater.read_current_state(session, trip_id)
                memories = self._updater.read_memory_context(session, trip_id)
                active_recommendation_context = None
                if recommendation_context is not None:
                    active_session = get_active_recommendation_session(
                        session, trip_id, recommendation_context.recommendation_session_id
                    )
                    if active_session is not None:
                        active_recommendation_context = {
                            "kind": active_session.kind, "query": active_session.query,
                            "recommendations": active_session.candidates,
                        }
                turn = self._manager_agent.decide(
                    current_state, user_message, trip_memories=memories,
                    conversation_context=conversation_context,
                    recommendation_context=active_recommendation_context,
                )
                if turn.tool is not TravelManagerTool.UPDATE_TRIP_STATE:
                    recommendations: list[TripRecommendationRead] = []
                    recommendation_session_id: UUID | None = None
                    assistant_message = self._manager_agent.direct_reply(turn, current_state)
                    if turn.tool is TravelManagerTool.SEARCH_RECOMMENDATIONS and self._recommendation_service is not None:
                        recommendation_session_id, recommendations = self._recommendation_service.create_session(
                            session, trip_id, current_state, turn.recommendation_kind,
                            keyword=turn.decision.recommendation_query,
                        )
                        noun = "酒店" if turn.recommendation_kind == "accommodation" else "景点"
                        assistant_message = (
                            f"我找到了 {len(recommendations)} 个附近{noun}，"
                            "你可以在下方卡片或地图上比较位置后直接点击选择。"
                            if recommendations else f"暂时没有找到可确认的附近{noun}。"
                        )
                    if commit:
                        session.commit()
                    return TripStateConversationResult(
                        state=current_state,
                        location_failures=[],
                        assessment=assess_trip_state(current_state),
                        clarification=TripStateClarification(),
                        assistant_message=assistant_message,
                        recommendations=recommendations,
                        recommendation_session_id=recommendation_session_id,
                    )
                update_result = self._updater.execute_decision(
                    session, trip_id, current_state, turn.decision,
                    expected_revision=expected_revision, commit=False, refresh_empty=False,
                )
                assistant_message = self._manager_agent.reply_after_tools(update_result)
                if commit:
                    session.commit()
                return TripStateConversationResult(
                    state=update_result.state,
                    location_failures=update_result.location_failures,
                    assessment=update_result.assessment,
                    clarification=TripStateClarification(),
                    assistant_message=assistant_message,
                    recommendations=[],
                )
            update_result = self._updater.update(
                session, trip_id, user_message, expected_revision=expected_revision, commit=False
            )
            if update_result.assistant_message is not None:
                clarification = TripStateClarification()
            else:
                try:
                    clarification = self._clarifier.generate(update_result)
                except LlmProviderError:
                    clarification = TripStateClarification()
            assistant_message = update_result.assistant_message
            if update_result.executed_tools and self._reply_generator is not None:
                assistant_message = self._reply_generator.generate(update_result, clarification)
            if commit:
                session.commit()
        except Exception:
            if commit:
                session.rollback()
            raise
        return TripStateConversationResult(
            state=update_result.state,
            location_failures=update_result.location_failures,
            assessment=update_result.assessment,
            clarification=clarification,
            assistant_message=assistant_message,
            recommendations=[],
        )
