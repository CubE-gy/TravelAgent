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


class TripStateUpdater(Protocol):
    """The state-update capability needed by the conversation service."""

    def update(
        self, session: Session, trip_id: UUID, user_message: str, *, commit: bool = True
    ) -> TripStateUpdateResult: ...


class TripStateClarifier(Protocol):
    """The clarification capability needed after a state update."""

    def generate(self, update_result: TripStateUpdateResult) -> TripStateClarification: ...


@dataclass(frozen=True)
class TripStateConversationResult:
    """The complete result of handling one user message for one Trip."""

    state: TripState
    location_failures: list[LocationResolutionFailure]
    assessment: TripStateAssessment
    clarification: TripStateClarification


class TripStateConversationService:
    """Coordinate state updating and necessary clarification generation."""

    def __init__(self, updater: TripStateUpdater, clarifier: TripStateClarifier) -> None:
        self._updater = updater
        self._clarifier = clarifier

    def handle(
        self, session: Session, trip_id: UUID, user_message: str, *, commit: bool = True
    ) -> TripStateConversationResult:
        """Update one Trip then generate only its required clarification questions."""
        try:
            update_result = self._updater.update(
                session, trip_id, user_message, commit=False
            )
            clarification = self._clarifier.generate(update_result)
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
        )
