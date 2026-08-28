from uuid import uuid4

import pytest

from app.schemas.trip_state import TripState
from app.schemas.trip_state_clarification import TripStateClarification
from app.services.trip_state_assessor import assess_trip_state
from app.services.trip_state_conversation_service import TripStateConversationService
from app.services.trip_state_update_service import TripStateUpdateResult


class FakeUpdater:
    def __init__(self, result: TripStateUpdateResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[object, object, str, int, bool]] = []

    def update(
        self,
        session: object,
        trip_id: object,
        user_message: str,
        *,
        expected_revision: int,
        commit: bool = True,
    ) -> TripStateUpdateResult:
        self.calls.append((session, trip_id, user_message, expected_revision, commit))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeClarifier:
    def __init__(self, result: TripStateClarification) -> None:
        self.result = result
        self.calls: list[TripStateUpdateResult] = []

    def generate(self, update_result: TripStateUpdateResult) -> TripStateClarification:
        self.calls.append(update_result)
        return self.result


class FailingClarifier:
    def generate(self, update_result: TripStateUpdateResult) -> TripStateClarification:
        del update_result
        raise RuntimeError("clarification failed")


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


def update_result(state: TripState) -> TripStateUpdateResult:
    return TripStateUpdateResult(
        state=state,
        location_failures=[],
        assessment=assess_trip_state(state),
    )


def test_handle_updates_state_then_returns_generated_clarification() -> None:
    trip_id = uuid4()
    state = TripState(trip_id=trip_id, destination={"query": "北京"})
    updater_result = update_result(state)
    updater = FakeUpdater(updater_result)
    clarification = TripStateClarification(questions=[])
    clarifier = FakeClarifier(clarification)
    session = FakeSession()

    result = TripStateConversationService(updater, clarifier).handle(
        session, trip_id, "去北京", expected_revision=0
    )

    assert updater.calls == [(session, trip_id, "去北京", 0, False)]
    assert clarifier.calls == [updater_result]
    assert result.state == state
    assert result.assessment == updater_result.assessment
    assert result.location_failures == []
    assert result.clarification == clarification
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_handle_does_not_generate_clarification_when_state_update_fails() -> None:
    updater = FakeUpdater(RuntimeError("update failed"))
    clarifier = FakeClarifier(TripStateClarification())

    with pytest.raises(RuntimeError, match="update failed"):
        TripStateConversationService(updater, clarifier).handle(
            FakeSession(), uuid4(), "去北京", expected_revision=0
        )

    assert clarifier.calls == []


def test_handle_rolls_back_uncommitted_state_when_clarification_fails() -> None:
    session = FakeSession()
    updater = FakeUpdater(
        update_result(TripState(trip_id=uuid4(), destination={"query": "北京"}))
    )

    with pytest.raises(RuntimeError, match="clarification failed"):
        TripStateConversationService(updater, FailingClarifier()).handle(
            session, uuid4(), "去北京", expected_revision=0
        )

    assert updater.calls[0][-1] is False
    assert session.commit_calls == 0
    assert session.rollback_calls == 1
