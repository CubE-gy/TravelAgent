"""Orchestration of one conversational TripState update."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories.trip import get_trip_by_id, sync_trip_dates_from_state
from app.repositories.trip_state import (
    TripStateRevisionConflictError,
    get_trip_state,
    save_trip_state,
)
from app.schemas.trip_state import TripState, TripStateLocationField
from app.schemas.trip_state_operation import (
    TripStateLocationConfirmationOperation,
    TripStateOperation,
    TripStatePatchOperation,
)
from app.schemas.trip_state_assessment import TripStateAssessment
from app.services.trip_state_assessor import assess_trip_state
from app.services.trip_state_location_resolution_service import (
    LocationResolutionFailure,
    TripStateLocationResolutionResult,
)
from app.services.trip_state_extraction_service import TripStateMessageUnderstanding
from app.services.trip_state_merger import merge_trip_state


class TripStateExtractor(Protocol):
    """The extraction capability needed to turn one message into a state patch."""

    def extract(
        self, current_state: TripState, user_message: str
    ) -> TripStateMessageUnderstanding: ...


class TripStateLocationResolver(Protocol):
    """The location-normalization capability used before state persistence."""

    def resolve(self, state: TripState) -> TripStateLocationResolutionResult: ...


class TripStateLocationConfirmer(Protocol):
    """The validated candidate-confirmation capability used during a message update."""

    def apply(
        self,
        state: TripState,
        field: TripStateLocationField,
        selected_poi_id: str,
        place_index: int | None = None,
    ) -> TripState: ...


@dataclass(frozen=True)
class TripStateUpdateResult:
    """The persisted state and any non-destructive location lookup failures."""

    state: TripState
    location_failures: list[LocationResolutionFailure]
    assessment: TripStateAssessment


class TripStateUpdateService:
    """Extract, merge, normalize, and persist one user-requested state update."""

    def __init__(
        self,
        extractor: TripStateExtractor,
        location_resolver: TripStateLocationResolver,
        location_confirmer: TripStateLocationConfirmer | None = None,
    ) -> None:
        self._extractor = extractor
        self._location_resolver = location_resolver
        self._location_confirmer = location_confirmer

    def update(
        self,
        session: Session,
        trip_id: UUID,
        user_message: str,
        *,
        expected_revision: int,
        commit: bool = True,
    ) -> TripStateUpdateResult:
        """Persist only after extraction, merging, and map normalization succeed."""
        try:
            current_state = get_trip_state(session, trip_id)
            if current_state is None:
                trip = get_trip_by_id(session, trip_id)
                if trip is None:
                    raise ValueError("Trip not found")
                current_state = TripState(
                    trip_id=trip_id,
                    departure_date=trip.start_date,
                    return_date=trip.end_date,
                )
            self._require_expected_revision(current_state, expected_revision)
            understanding = self._extractor.extract(current_state, user_message)
            updated_state = self._apply_operations(current_state, understanding.operations())
            resolution_result = self._location_resolver.resolve(updated_state)
            persisted_state = save_trip_state(
                session,
                resolution_result.state,
                expected_revision=expected_revision,
            )
            sync_trip_dates_from_state(
                session,
                trip_id,
                start_date=persisted_state.departure_date,
                end_date=persisted_state.return_date,
            )
            if commit:
                session.commit()
        except Exception:
            if commit:
                session.rollback()
            raise
        return TripStateUpdateResult(
            state=persisted_state,
            location_failures=resolution_result.failures,
            assessment=assess_trip_state(persisted_state),
        )

    @staticmethod
    def _require_expected_revision(state: TripState, expected_revision: int) -> None:
        if expected_revision != state.revision:
            raise TripStateRevisionConflictError(
                expected_revision=expected_revision,
                current_revision=state.revision,
            )

    def _apply_operations(
        self,
        current_state: TripState,
        operations: tuple[TripStateOperation, ...],
    ) -> TripState:
        """Apply operations in declared order before location normalization."""
        updated_state = current_state
        for operation in operations:
            if isinstance(operation, TripStatePatchOperation):
                updated_state = merge_trip_state(updated_state, operation.patch)
                continue
            if self._location_confirmer is None:
                raise RuntimeError("location confirmation capability is not configured")
            updated_state = self._location_confirmer.apply(
                updated_state,
                operation.field,
                operation.selected_poi_id,
                operation.place_index,
            )
        return updated_state
