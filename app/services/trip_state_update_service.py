"""Orchestration of one conversational TripState update."""

from dataclasses import dataclass
from typing import Callable, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories.trip_memory import forget_trip_memory, upsert_trip_memory
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
from app.services.llm_provider import LlmProviderError
from app.services.trip_state_merger import merge_trip_state


class TripStateExtractor(Protocol):
    """The extraction capability needed to turn one message into a state patch."""

    def extract(
        self,
        current_state: TripState,
        user_message: str,
        trip_memories: list[dict[str, object]] | None = None,
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
    assistant_message: str | None = None
    executed_tools: bool = False


class TripStateUpdateService:
    """Extract, merge, normalize, and persist one user-requested state update."""

    def __init__(
        self,
        extractor: TripStateExtractor,
        location_resolver: TripStateLocationResolver,
        location_confirmer: TripStateLocationConfirmer | None = None,
        memory_reader: Callable[[Session, UUID], list[object]] | None = None,
    ) -> None:
        self._extractor = extractor
        self._location_resolver = location_resolver
        self._location_confirmer = location_confirmer
        self._memory_reader = memory_reader or (lambda session, trip_id: [])

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
            current_state = self.read_current_state(session, trip_id)
            self._require_expected_revision(current_state, expected_revision)
            memory_context = [
                {"category": memory.category, "key": memory.key, "value": memory.value}
                for memory in self._memory_reader(session, trip_id)
            ]
            try:
                understanding = self._extractor.extract(current_state, user_message, memory_context)
            except LlmProviderError:
                return TripStateUpdateResult(
                    state=current_state,
                    location_failures=[],
                    assessment=assess_trip_state(current_state),
                    assistant_message="我可以继续帮你处理这趟旅行的地点、酒店、交通和偏好。",
                )
            if understanding.intent.value in {"conversation", "out_of_scope"}:
                return TripStateUpdateResult(
                    state=current_state,
                    location_failures=[],
                    assessment=assess_trip_state(current_state),
                    assistant_message=understanding.assistant_message,
                )
            return self.execute_decision(
                session, trip_id, current_state, understanding,
                expected_revision=expected_revision, commit=commit, refresh_empty=True,
            )
        except Exception:
            if commit:
                session.rollback()
            raise
        raise AssertionError("unreachable")

    @staticmethod
    def read_current_state(session: Session, trip_id: UUID) -> TripState:
        """Read the state tool's input, creating only an in-memory initial state."""
        current_state = get_trip_state(session, trip_id)
        if current_state is not None:
            return current_state
        trip = get_trip_by_id(session, trip_id)
        if trip is None:
            raise ValueError("Trip not found")
        return TripState(
            trip_id=trip_id, departure_date=trip.start_date, return_date=trip.end_date
        )

    def execute_decision(
        self,
        session: Session,
        trip_id: UUID,
        current_state: TripState,
        understanding: TripStateMessageUnderstanding,
        *,
        expected_revision: int,
        commit: bool = True,
        refresh_empty: bool = False,
    ) -> TripStateUpdateResult:
        """Execute only the validated state, memory, and map tools in one transaction."""
        self._require_expected_revision(current_state, expected_revision)
        if understanding.intent.value != "state_update":
            raise ValueError("only state_update decisions may execute travel tools")
        try:
            executed_tools = bool(understanding.operations() or understanding.memory_instructions)
            self._apply_memory_instructions(session, trip_id, understanding)
            if not understanding.operations() and (
                understanding.memory_instructions or not refresh_empty
            ):
                if commit:
                    session.commit()
                return TripStateUpdateResult(
                    state=current_state,
                    location_failures=[],
                    assessment=assess_trip_state(current_state),
                    executed_tools=executed_tools,
                )
            updated_state = self._apply_operations(current_state, understanding.operations())
            resolution_result = self._location_resolver.resolve(updated_state)
            persisted_state = save_trip_state(
                session, resolution_result.state, expected_revision=expected_revision
            )
            sync_trip_dates_from_state(
                session, trip_id, start_date=persisted_state.departure_date,
                end_date=persisted_state.return_date,
            )
            if commit:
                session.commit()
            return TripStateUpdateResult(
                state=persisted_state,
                location_failures=resolution_result.failures,
                assessment=assess_trip_state(persisted_state),
                executed_tools=executed_tools,
            )
        except Exception:
            if commit:
                session.rollback()
            raise

    def read_memory_context(self, session: Session, trip_id: UUID) -> list[dict[str, object]]:
        """Expose only persisted, user-confirmed memory to the Manager Agent."""
        return [
            {"category": memory.category, "key": memory.key, "value": memory.value}
            for memory in self._memory_reader(session, trip_id)
        ]

    @staticmethod
    def _apply_memory_instructions(
        session: Session, trip_id: UUID, understanding: TripStateMessageUnderstanding
    ) -> None:
        """Persist only the bounded, explicit memory operations in this decision."""
        for instruction in understanding.memory_instructions:
            if instruction.action == "forget":
                forget_trip_memory(session, trip_id, instruction.category, instruction.key)
            else:
                assert instruction.value is not None
                upsert_trip_memory(
                    session,
                    trip_id,
                    instruction.category,
                    instruction.key,
                    {"text": instruction.value},
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
