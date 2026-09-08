from uuid import uuid4

from pydantic import BaseModel

from app.schemas.trip_conversation_turn import AgentTurnTrace, LocationFailureTrace
from app.services.llm_call_tracer import TracingLlmProvider
from app.services.llm_provider import (
    LlmMessage,
    LlmMessageRole,
    MockLlmProvider,
)
from app.services.trip_turn_store import TripTurnStore


class SampleDecision(BaseModel):
    value: str


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
    """The minimal Session surface used by the turn repository."""

    def __init__(self, stored_turns: list[StoredTurn] | None = None) -> None:
        self.added: list[object] = []
        self.flush_calls = 0
        self.stored_turns = stored_turns or []

    def add(self, record: object) -> None:
        self.added.append(record)

    def flush(self) -> None:
        self.flush_calls += 1

    def scalar(self, statement: object) -> int:
        del statement
        return len(self.added)

    def scalars(self, statement: object) -> FakeResult:
        del statement
        return FakeResult(list(reversed(self.stored_turns)))


def _traced_provider() -> TracingLlmProvider:
    tracer = TracingLlmProvider(MockLlmProvider({"value": "ok"}))
    tracer.generate_structured(
        [LlmMessage(role=LlmMessageRole.USER, content="我要去北京")], SampleDecision
    )
    return tracer


def test_record_writes_one_turn_with_traced_llm_calls() -> None:
    session = FakeSession()
    trip_id = uuid4()

    record = TripTurnStore(_traced_provider()).record(
        session,
        trip_id,
        user_message="我要去北京",
        assistant_message="已记录目的地。",
        state_revision=3,
        trace=AgentTurnTrace(decision="update_trip_state", operations=["apply_patch"]),
    )

    assert session.added == [record]
    assert session.flush_calls == 1
    assert record.trip_id == trip_id
    assert record.turn_index == 0
    assert record.user_message == "我要去北京"
    assert record.assistant_message == "已记录目的地。"
    assert record.state_revision == 3
    assert record.trace["decision"] == "update_trip_state"
    assert record.trace["operations"] == ["apply_patch"]
    assert record.trace["llm_calls"] == [
        {"response_model": "SampleDecision",
         "latency_ms": record.trace["llm_calls"][0]["latency_ms"],
         "error": None}
    ]


def test_record_keeps_an_empty_call_list_without_a_tracer() -> None:
    session = FakeSession()

    record = TripTurnStore().record(
        session,
        uuid4(),
        user_message="就这些",
        assistant_message=None,
        state_revision=0,
        trace=AgentTurnTrace(decision="final_response"),
    )

    assert record.trace["llm_calls"] == []
    assert record.assistant_message is None


def test_record_does_not_overwrite_the_turn_trace_it_was_given() -> None:
    tracer = _traced_provider()
    session = FakeSession()
    trace = AgentTurnTrace(decision="final_response")

    TripTurnStore(tracer).record(
        session, uuid4(), user_message="你好", assistant_message="你好", state_revision=0, trace=trace
    )

    assert trace.llm_calls == []


def test_read_recent_turns_renders_stored_turns_in_chronological_order() -> None:
    session = FakeSession([
        StoredTurn("我要去北京", "已记录目的地。"),
        StoredTurn("住国贸附近", "已记录住宿。"),
    ])

    assert TripTurnStore().read_recent_turns(session, uuid4()).dialogue == [
        {"role": "user", "content": "我要去北京"},
        {"role": "assistant", "content": "已记录目的地。"},
        {"role": "user", "content": "住国贸附近"},
        {"role": "assistant", "content": "已记录住宿。"},
    ]


def test_read_recent_turns_skips_turns_without_an_assistant_reply() -> None:
    session = FakeSession([StoredTurn("就这些", None)])

    assert TripTurnStore().read_recent_turns(session, uuid4()).dialogue == [
        {"role": "user", "content": "就这些"}
    ]


def test_read_recent_turns_returns_nothing_for_a_trip_without_turns() -> None:
    history = TripTurnStore().read_recent_turns(FakeSession(), uuid4())

    assert history.dialogue == []
    assert history.facts == []


def test_read_recent_turns_reports_what_each_turn_did() -> None:
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
        ),
        StoredTurn(
            "住新街口附近",
            "我找到了 3 个附近酒店。",
            AgentTurnTrace(decision="search_recommendations", recommendation_count=3),
            turn_index=2,
        ),
    ])

    assert TripTurnStore().read_recent_turns(session, uuid4()).facts == [
        {
            "turn_index": 1,
            "user_message": "加上中山陵，还有火星博物馆",
            "decision": "update_trip_state",
            "operations": ["apply_patch"],
            "location_failures": ["places/火星博物馆"],
            "recommendation_count": 0,
        },
        {
            "turn_index": 2,
            "user_message": "住新街口附近",
            "decision": "search_recommendations",
            "operations": [],
            "location_failures": [],
            "recommendation_count": 3,
        },
    ]


def test_read_recent_turns_truncates_long_user_messages_in_facts_only() -> None:
    long_message = "去" * 80
    session = FakeSession([StoredTurn(long_message, "好的。")])
    history = TripTurnStore().read_recent_turns(session, uuid4())

    assert history.dialogue[0]["content"] == long_message
    assert history.facts[0]["user_message"] == "去" * 40
