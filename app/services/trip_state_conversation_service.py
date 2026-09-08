"""Unified Stage 2 conversational handling for one Trip."""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.schemas.trip_state import TripState
from app.schemas.trip_state_assessment import TripStateAssessment
from app.schemas.trip_state_clarification import TripStateClarification
from app.schemas.trip_conversation_turn import AgentTurnTrace, LocationFailureTrace
from app.services.trip_state_location_resolution_service import LocationResolutionFailure
from app.services.trip_state_update_service import TripStateUpdateResult
from app.services.llm_provider import LlmProviderError
from app.services.travel_manager_agent import TravelManagerAgent
from app.services.travel_tool import ToolContext, ToolObservation
from app.services.trip_turn_store import TripTurnHistory, TripTurnStore
from app.services.trip_state_assessor import assess_trip_state
from app.schemas.trip_recommendation import TripRecommendationContext, TripRecommendationRead
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

    def read_current_state(self, session: Session, trip_id: UUID) -> TripState: ...

    def read_memory_context(self, session: Session, trip_id: UUID) -> list[dict[str, object]]: ...


class TripStateClarifier(Protocol):
    """The clarification capability needed after a state update."""

    def generate(self, update_result: TripStateUpdateResult) -> TripStateClarification: ...


def _failure_traces(
    failures: list[LocationResolutionFailure],
) -> list[LocationFailureTrace]:
    """Keep the failing query itself; a bare count cannot inform a later turn."""
    return [
        LocationFailureTrace(field=failure.field, query=failure.query, error_code=failure.error_code)
        for failure in failures
    ]


def _observation_location_failures(
    observation: ToolObservation,
) -> list[LocationResolutionFailure]:
    """Recover the original failure list from an update tool's observation."""
    return [
        LocationResolutionFailure(**entry)
        for entry in observation.data.get("location_failures", [])
    ]


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
    trace: AgentTurnTrace = field(default_factory=AgentTurnTrace)


class TripStateConversationService:
    """Coordinate state updating and necessary clarification generation."""

    def __init__(
        self,
        updater: TripStateUpdater,
        clarifier: TripStateClarifier,
        reply_generator=None,
        manager_agent: TravelManagerAgent | None = None,
        turn_store: TripTurnStore | None = None,
    ) -> None:
        self._updater = updater
        self._clarifier = clarifier
        self._reply_generator = reply_generator
        self._manager_agent = manager_agent
        self._turn_store = turn_store

    def _resolve_history(
        self,
        session: Session,
        trip_id: UUID,
        conversation_context: list[dict[str, str]] | None,
    ) -> TripTurnHistory | None:
        """Prefer persisted turns; a client-supplied context is the fallback.

        A client-supplied context carries no structured outcome facts, so those
        are only available when the turns come from the server-side store.
        """
        if conversation_context:
            return TripTurnHistory(dialogue=conversation_context, facts=[])
        if self._turn_store is None:
            return None
        return self._turn_store.read_recent_turns(session, trip_id)

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
                recent_turns = self._resolve_history(session, trip_id, conversation_context)
                history = recent_turns.dialogue if recent_turns else None
                turn_facts = recent_turns.facts if recent_turns else None
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
                    conversation_context=history,
                    turn_facts=turn_facts,
                    recommendation_context=active_recommendation_context,
                )
                if turn.tool is None:
                    assistant_message = self._manager_agent.direct_reply(turn, current_state)
                    if commit:
                        session.commit()
                    return self._record_turn(
                        session, trip_id, user_message,
                        TripStateConversationResult(
                            state=current_state,
                            location_failures=[],
                            assessment=assess_trip_state(current_state),
                            clarification=TripStateClarification(),
                            assistant_message=assistant_message,
                            trace=AgentTurnTrace(decision="final_response"),
                        ),
                    )
                tool_context = ToolContext(
                    session=session, trip_id=trip_id,
                    current_state=current_state, expected_revision=expected_revision,
                )
                observation = self._manager_agent.run_tool(turn, tool_context)
                post_state = self._post_state_from_observation(observation, current_state)
                assistant_message = self._manager_agent.reply_after_tools(
                    observation, current_state=post_state,
                    user_message=user_message, conversation_context=history,
                    turn_facts=turn_facts,
                )
                if commit:
                    session.commit()
                location_failures = _observation_location_failures(observation)
                return self._record_turn(
                    session, trip_id, user_message,
                    TripStateConversationResult(
                        state=post_state,
                        location_failures=location_failures,
                        assessment=assess_trip_state(post_state),
                        clarification=TripStateClarification(),
                        assistant_message=assistant_message,
                        recommendations=self._recommendation_payload(observation),
                        recommendation_session_id=self._recommendation_session_id(observation),
                        trace=AgentTurnTrace(
                            decision=turn.decision.tool_name,
                            operations=[
                                op.kind.value for op in turn.decision.operations()
                            ],
                            location_failures=_failure_traces(location_failures),
                            recommendation_count=self._recommendation_count(observation),
                        ),
                    ),
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
                assistant_message = self._reply_generator.generate(
                    ToolObservation(
                        summary="update_trip_state",
                        data={"location_failures": [
                            failure.__dict__ for failure in update_result.location_failures
                        ]},
                    ),
                    current_state=update_result.state, clarification=clarification,
                )
            if commit:
                session.commit()
        except Exception:
            if commit:
                session.rollback()
            raise
        return self._record_turn(
            session, trip_id, user_message,
            TripStateConversationResult(
                state=update_result.state,
                location_failures=update_result.location_failures,
                assessment=update_result.assessment,
                clarification=clarification,
                assistant_message=assistant_message,
                recommendations=[],
                trace=AgentTurnTrace(
                    decision="update_trip_state" if update_result.executed_tools else "final_response",
                    location_failures=_failure_traces(update_result.location_failures),
                ),
            ),
        )

    @staticmethod
    def _post_state_from_observation(
        observation: ToolObservation, current_state: TripState
    ) -> TripState:
        """Carry the post-tool state forward so the reply model sees a fresh snapshot."""
        serialized_state = observation.data.get("state")
        if isinstance(serialized_state, dict):
            return TripState.model_validate(serialized_state)
        new_revision = observation.data.get("state_revision")
        if isinstance(new_revision, int):
            return current_state.model_copy(update={"revision": new_revision})
        return current_state

    @staticmethod
    def _recommendation_payload(observation: ToolObservation) -> list[dict[str, object]]:
        candidates = observation.data.get("candidates") or []
        if not candidates:
            return []
        return [
            TripRecommendationRead(
                kind=observation.data.get("kind", "places"),
                location=_candidate_to_location(candidate),
            )
            for candidate in candidates
        ]

    @staticmethod
    def _recommendation_session_id(observation: ToolObservation) -> UUID | None:
        value = observation.data.get("session_id")
        if value is None:
            return None
        return UUID(str(value))

    @staticmethod
    def _recommendation_count(observation: ToolObservation) -> int:
        candidates = observation.data.get("candidates") or []
        return len(candidates)

    def _record_turn(
        self,
        session: Session,
        trip_id: UUID,
        user_message: str,
        result: TripStateConversationResult,
    ) -> TripStateConversationResult:
        """Persist the finished turn in the caller's transaction when recording is on."""
        if self._turn_store is None:
            return result
        self._turn_store.record(
            session,
            trip_id,
            user_message=user_message,
            assistant_message=result.assistant_message,
            state_revision=result.state.revision,
            trace=result.trace,
        )
        return result


def _candidate_to_location(candidate: dict[str, object]):
    """Reconstruct a ResolvedLocation from a serialized search candidate."""
    from app.schemas.map import ResolvedLocation

    return ResolvedLocation(
        poi_id=str(candidate.get("poi_id", "")),
        name=str(candidate.get("name", "")),
        address=candidate.get("address") and str(candidate.get("address")),
        category_name=candidate.get("category") and str(candidate.get("category")),
        coordinate=candidate.get("coordinate") or {"latitude": 0.0, "longitude": 0.0},
    )
