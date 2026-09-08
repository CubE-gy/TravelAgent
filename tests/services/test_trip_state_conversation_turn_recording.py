from uuid import uuid4

from app.schemas.trip_state import TripState, TripStatePatch
from app.schemas.trip_state_clarification import TripStateClarification
from app.services.travel_manager_agent import TravelManagerTurn
from app.services.trip_state_assessor import assess_trip_state
from app.schemas.trip_conversation_turn import AgentTurnTrace, LocationFailureTrace
from app.services.travel_tool import ToolObservation
from app.services.trip_state_conversation_service import TripStateConversationService
from app.services.trip_state_extraction_service import (
    AgentDecision,
    TripStateMessageIntent,
)
from app.services.trip_state_location_resolution_service import LocationResolutionFailure
from app.services.trip_state_update_service import TripStateUpdateResult
from app.services.trip_turn_store import TripTurnStore


class FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class StoredTurn:
    def __init__(
        self,
        user_message: str,
        assistant_message: str | None,
        trace: AgentTurnTrace | None = None,
        turn_index: int = 0,
    ) -> None:
        self.user_message = user_message
        self.assistant_message = assistant_message
        self.trace = (trace or AgentTurnTrace()).model_dump(mode="json")
        self.turn_index = turn_index


class FakeSession:
    def __init__(self, stored_turns: list[StoredTurn] | None = None) -> None:
        self.added: list[object] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.stored_turns = stored_turns or []

    def add(self, record: object) -> None:
        self.added.append(record)

    def flush(self) -> None:
        return None

    def scalar(self, statement: object) -> int:
        del statement
        return len(self.added)

    def scalars(self, statement: object) -> FakeResult:
        del statement
        return FakeResult(list(reversed(self.stored_turns)))

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


class FakeUpdater:
    def __init__(self, result: TripStateUpdateResult) -> None:
        self.result = result

    def update(
        self,
        session: object,
        trip_id: object,
        user_message: str,
        *,
        expected_revision: int,
        commit: bool = True,
    ) -> TripStateUpdateResult:
        return self.result


class FakeClarifier:
    def generate(self, update_result: TripStateUpdateResult) -> TripStateClarification:
        return TripStateClarification()


class FakeDecisionUpdater:
    def __init__(self, state: TripState, result: TripStateUpdateResult) -> None:
        self._state = state
        self.result = result

    def read_current_state(self, session: object, trip_id: object) -> TripState:
        return self._state

    def read_memory_context(self, session: object, trip_id: object) -> list[dict[str, object]]:
        return []

    def execute_decision(
        self,
        session: object,
        trip_id: object,
        current_state: TripState,
        decision: AgentDecision,
        *,
        expected_revision: int,
        commit: bool = True,
        refresh_empty: bool = False,
    ) -> TripStateUpdateResult:
        return self.result


class FakeManagerAgent:
    def __init__(self, decision: AgentDecision, *, reply: str = "已更新行程。", failures=None) -> None:
        self._turn = TravelManagerTurn(decision)
        self._reply = reply
        self._failures = failures or []
        self.history: list[dict[str, str]] | None = None
        self.turn_facts: list[dict[str, object]] | None = None
        self.reply_turn_facts: list[dict[str, object]] | None = None
        self.last_observation: object | None = None

    def decide(self, *args: object, **kwargs: object) -> TravelManagerTurn:
        self.history = kwargs.get("conversation_context")  # type: ignore[assignment]
        self.turn_facts = kwargs.get("turn_facts")  # type: ignore[assignment]
        return self._turn

    def direct_reply(self, turn: TravelManagerTurn, state: TripState) -> str:
        return turn.decision.assistant_message or ""

    def run_tool(self, turn: TravelManagerTurn, context: object) -> ToolObservation:
        return ToolObservation(
            summary="update_trip_state: revision 0 -> 1",
            data={
                "state_revision": 1,
                "location_failures": [failure.__dict__ for failure in self._failures],
                "executed_operations": [
                    operation.kind.value for operation in self._turn.decision.operations()
                ],
            },
        )

    def reply_after_tools(
        self,
        observation,
        *,
        current_state,
        user_message: str | None = None,
        conversation_context: list[dict[str, str]] | None = None,
        turn_facts: list[dict[str, object]] | None = None,
        clarification=None,
    ) -> str:
        self.last_observation = observation
        self.reply_turn_facts = turn_facts
        return self._reply


def _update_result(state: TripState, failures: list[LocationResolutionFailure] | None = None) -> TripStateUpdateResult:
    return TripStateUpdateResult(
        state=state,
        location_failures=failures or [],
        assessment=assess_trip_state(state),
        executed_tools=True,
    )


def test_legacy_path_records_one_turn_with_the_state_revision() -> None:
    trip_id = uuid4()
    state = TripState(trip_id=trip_id, revision=4, destination={"query": "南京"})
    session = FakeSession()
    service = TripStateConversationService(
        FakeUpdater(_update_result(state)),
        FakeClarifier(),
        turn_store=TripTurnStore(),
    )

    result = service.handle(session, trip_id, "去南京", expected_revision=4)

    assert len(session.added) == 1
    turn = session.added[0]
    assert turn.trip_id == trip_id
    assert turn.user_message == "去南京"
    assert turn.state_revision == 4
    assert turn.trace["decision"] == "update_trip_state"
    assert result.trace.decision == "update_trip_state"


def test_recorded_turn_keeps_the_failing_location_query() -> None:
    trip_id = uuid4()
    state = TripState(trip_id=trip_id, destination={"query": "南京"})
    failures = [
        LocationResolutionFailure(field="destination", query="南京", error_code="upstream_error")
    ]
    session = FakeSession()
    service = TripStateConversationService(
        FakeUpdater(_update_result(state, failures)),
        FakeClarifier(),
        turn_store=TripTurnStore(),
    )

    service.handle(session, trip_id, "去南京", expected_revision=0)

    assert session.added[0].trace["location_failures"] == [
        {"field": "destination", "query": "南京", "error_code": "upstream_error"}
    ]


def test_manager_path_records_the_direct_reply_decision() -> None:
    trip_id = uuid4()
    state = TripState(trip_id=trip_id)
    decision = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="final_response",
        assistant_message="南京的中山陵值得去。",
    )
    session = FakeSession()
    service = TripStateConversationService(
        FakeDecisionUpdater(state, _update_result(state)),
        FakeClarifier(),
        manager_agent=FakeManagerAgent(decision),
        turn_store=TripTurnStore(),
    )

    result = service.handle(session, trip_id, "有什么推荐？", expected_revision=0)

    assert result.trace.decision == "final_response"
    assert session.added[0].trace["decision"] == "final_response"
    assert session.added[0].assistant_message == "南京的中山陵值得去。"


def test_manager_path_records_the_operations_it_executed() -> None:
    trip_id = uuid4()
    state = TripState(trip_id=trip_id, revision=2)
    decision = AgentDecision(
        patch=TripStatePatch(destination={"query": "南京"}),
        tool_name="update_trip_state",
    )
    session = FakeSession()
    service = TripStateConversationService(
        FakeDecisionUpdater(state, _update_result(state)),
        FakeClarifier(),
        manager_agent=FakeManagerAgent(decision),
        turn_store=TripTurnStore(),
    )

    result = service.handle(session, trip_id, "去南京", expected_revision=2)

    assert result.trace.operations == ["apply_patch"]
    assert session.added[0].trace["operations"] == ["apply_patch"]
    assert session.added[0].assistant_message == "已更新行程。"


def test_without_a_recorder_no_turn_is_written() -> None:
    trip_id = uuid4()
    state = TripState(trip_id=trip_id)
    session = FakeSession()
    service = TripStateConversationService(FakeUpdater(_update_result(state)), FakeClarifier())

    service.handle(session, trip_id, "去南京", expected_revision=0)

    assert session.added == []


def _final_response_decision() -> AgentDecision:
    return AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="final_response",
        assistant_message="南京的中山陵值得去。",
    )


def test_history_falls_back_to_persisted_turns_when_client_sends_none() -> None:
    trip_id = uuid4()
    state = TripState(trip_id=trip_id)
    session = FakeSession([
        StoredTurn("我要去北京", "已记录目的地。"),
        StoredTurn("住国贸附近", "已记录住宿。"),
    ])
    manager = FakeManagerAgent(_final_response_decision())
    service = TripStateConversationService(
        FakeDecisionUpdater(state, _update_result(state)),
        FakeClarifier(),
        manager_agent=manager,
        turn_store=TripTurnStore(),
    )

    service.handle(session, trip_id, "再加中山陵", expected_revision=0)

    assert manager.history == [
        {"role": "user", "content": "我要去北京"},
        {"role": "assistant", "content": "已记录目的地。"},
        {"role": "user", "content": "住国贸附近"},
        {"role": "assistant", "content": "已记录住宿。"},
    ]


def test_client_context_still_wins_when_it_is_supplied() -> None:
    trip_id = uuid4()
    state = TripState(trip_id=trip_id)
    session = FakeSession([StoredTurn("服务端历史", "服务端回复。")])
    manager = FakeManagerAgent(_final_response_decision())
    service = TripStateConversationService(
        FakeDecisionUpdater(state, _update_result(state)),
        FakeClarifier(),
        manager_agent=manager,
        turn_store=TripTurnStore(),
    )

    service.handle(
        session, trip_id, "再加中山陵", expected_revision=0,
        conversation_context=[{"role": "user", "content": "客户端历史"}],
    )

    assert manager.history == [{"role": "user", "content": "客户端历史"}]


def test_a_failed_turn_is_not_recorded() -> None:
    class FailingUpdater:
        def update(
            self,
            session: object,
            trip_id: object,
            user_message: str,
            *,
            expected_revision: int,
            commit: bool = True,
        ) -> TripStateUpdateResult:
            raise RuntimeError("update failed")

    session = FakeSession()
    service = TripStateConversationService(
        FailingUpdater(), FakeClarifier(), turn_store=TripTurnStore()
    )

    try:
        service.handle(session, uuid4(), "去南京", expected_revision=0)
    except RuntimeError:
        pass
    else:  # pragma: no cover - the call above must fail
        raise AssertionError("handle should propagate the updater failure")

    assert session.added == []
    assert session.rollback_calls == 1


def test_manager_receives_structured_turn_facts_from_the_store() -> None:
    trip_id = uuid4()
    state = TripState(trip_id=trip_id, revision=2)
    decision = AgentDecision(
        patch=TripStatePatch(destination={"query": "南京"}),
        tool_name="update_trip_state",
    )
    session = FakeSession([
        StoredTurn(
            "加上中山陵，还有火星博物馆",
            "已加上中山陵。",
            AgentTurnTrace(
                decision="update_trip_state",
                operations=["apply_patch"],
                location_failures=[
                    LocationFailureTrace(field="places", query="火星博物馆", error_code="NOT_FOUND")
                ],
            ),
            turn_index=1,
        )
    ])
    manager = FakeManagerAgent(decision)
    service = TripStateConversationService(
        FakeDecisionUpdater(state, _update_result(state)),
        FakeClarifier(),
        manager_agent=manager,
        turn_store=TripTurnStore(),
    )

    service.handle(session, trip_id, "去南京", expected_revision=2)

    assert manager.turn_facts == [
        {
            "turn_index": 1,
            "user_message": "加上中山陵，还有火星博物馆",
            "decision": "update_trip_state",
            "operations": ["apply_patch"],
            "location_failures": ["places/火星博物馆"],
            "recommendation_count": 0,
        }
    ]
    assert manager.reply_turn_facts == manager.turn_facts


def test_manager_path_records_failing_location_queries_from_the_tool() -> None:
    trip_id = uuid4()
    state = TripState(trip_id=trip_id, revision=1)
    decision = AgentDecision(
        patch=TripStatePatch(destination={"query": "南京"}),
        tool_name="update_trip_state",
    )
    failures = [LocationResolutionFailure(field="destination", query="南京", error_code="upstream_error")]
    session = FakeSession()
    service = TripStateConversationService(
        FakeDecisionUpdater(state, _update_result(state)),
        FakeClarifier(),
        manager_agent=FakeManagerAgent(decision, failures=failures),
        turn_store=TripTurnStore(),
    )

    service.handle(session, trip_id, "去南京", expected_revision=1)

    assert session.added[0].trace["location_failures"] == [
        {"field": "destination", "query": "南京", "error_code": "upstream_error"}
    ]


def test_reply_model_receives_search_candidates_from_the_tool_observation() -> None:
    trip_id = uuid4()
    state = TripState(trip_id=trip_id, revision=1)
    decision = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="search_recommendations",
        recommendation_kind="accommodation",
    )
    session = FakeSession()
    manager = FakeManagerAgent(decision, reply="金陵饭店在中山路1号。")
    # Make the manager tool produce a real-shaped search observation.
    def fake_run_tool(turn, context):  # type: ignore[no-redef]
        return ToolObservation(
            summary="search_recommendations: accommodation returned 1 candidates",
            data={"kind": "accommodation", "query": None, "session_id": str(uuid4()),
                  "candidates": [
                      {"poi_id": "B1", "name": "金陵饭店", "address": "中山路1号",
                       "category": "酒店", "coordinate": {"latitude": 32.04, "longitude": 118.78}}
                  ]},
        )
    manager.run_tool = fake_run_tool  # type: ignore[assignment]
    service = TripStateConversationService(
        FakeDecisionUpdater(state, _update_result(state)),
        FakeClarifier(),
        manager_agent=manager,
        turn_store=TripTurnStore(),
    )

    result = service.handle(session, trip_id, "找酒店", expected_revision=1)

    assert result.assistant_message == "金陵饭店在中山路1号。"
    assert result.recommendations and result.recommendations[0].location.name == "金陵饭店"
    assert manager.last_observation.summary.startswith("search_recommendations")
