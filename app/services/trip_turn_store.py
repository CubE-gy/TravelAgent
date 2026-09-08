"""Read and write the persisted conversation turns of one Trip."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.trip_conversation_turn import TripConversationTurnRecord
from app.repositories.trip_conversation_turn import (
    add_trip_conversation_turn,
    list_trip_conversation_turns,
)
from app.schemas.trip_conversation_turn import AgentTurnTrace, LlmCallTrace
from app.services.llm_call_tracer import TracingLlmProvider


HISTORY_TURN_LIMIT = 5
TURN_FACT_EXCERPT_LIMIT = 40


@dataclass(frozen=True)
class TripTurnHistory:
    """The dialogue of recent turns plus what each of them actually did."""

    dialogue: list[dict[str, str]] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)


class TripTurnStore:
    """Persist one handled turn and serve stored turns as Agent dialogue history."""

    def __init__(self, llm_tracer: TracingLlmProvider | None = None) -> None:
        self._llm_tracer = llm_tracer

    def record(
        self,
        session: Session,
        trip_id: object,
        *,
        user_message: str,
        assistant_message: str | None,
        state_revision: int,
        trace: AgentTurnTrace,
    ) -> TripConversationTurnRecord:
        """Store the turn in the caller's transaction, without committing."""
        llm_calls = (
            [
                LlmCallTrace(
                    response_model=record.response_model,
                    latency_ms=record.latency_ms,
                    error=record.error,
                )
                for record in self._llm_tracer.records
            ]
            if self._llm_tracer is not None
            else []
        )
        recorded_trace = trace.model_copy(update={"llm_calls": llm_calls})
        return add_trip_conversation_turn(
            session,
            trip_id,
            user_message=user_message,
            assistant_message=assistant_message,
            state_revision=state_revision,
            trace=recorded_trace.model_dump(mode="json"),
        )

    def read_recent_turns(self, session: Session, trip_id: object) -> TripTurnHistory:
        """Render stored turns as both dialogue and structured outcome facts.

        The dialogue alone only shows what was said. The facts section carries
        what the previous turns *did* -- which decision ran, which operations
        applied, and which locations the map could not confirm -- so a later
        decision does not have to infer it from the current state alone.
        """
        dialogue: list[dict[str, str]] = []
        facts: list[dict[str, Any]] = []
        for turn in list_trip_conversation_turns(
            session, trip_id, limit=HISTORY_TURN_LIMIT
        ):
            dialogue.append({"role": "user", "content": turn.user_message})
            if turn.assistant_message:
                dialogue.append({"role": "assistant", "content": turn.assistant_message})
            trace = AgentTurnTrace.model_validate(turn.trace)
            facts.append(
                {
                    "turn_index": turn.turn_index,
                    "user_message": turn.user_message[:TURN_FACT_EXCERPT_LIMIT],
                    "decision": trace.decision,
                    "operations": trace.operations,
                    "location_failures": [
                        f"{failure.field}/{failure.query}"
                        for failure in trace.location_failures
                    ],
                    "recommendation_count": trace.recommendation_count,
                }
            )
        return TripTurnHistory(dialogue=dialogue, facts=facts)
