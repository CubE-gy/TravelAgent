from uuid import uuid4

from app.schemas.trip_state import TripState, TripStatePatch
from app.schemas.trip_state_clarification import TripStateClarification
from app.services.travel_manager_agent import TravelManagerAgent
from app.services.trip_state_assessor import assess_trip_state
from app.services.trip_state_conversation_service import TripStateConversationService
from app.services.trip_state_extraction_service import AgentDecision, TripStateMessageIntent
from app.services.trip_state_update_service import TripStateUpdateResult
from app.services.llm_provider import LlmResponseError


class FakePlanner:
    def __init__(self, decision: AgentDecision) -> None:
        self.decision = decision
        self.calls: list[tuple[TripState, str, list[dict[str, object]], list[dict[str, str]] | None]] = []

    def extract(self, state, message, memories=None, conversation_context=None, recommendation_context=None):
        self.calls.append((state, message, memories or [], conversation_context))
        return self.decision


class FailingPlanner:
    def extract(self, *args, **kwargs):
        raise LlmResponseError("invalid response")


class FakeReplyGenerator:
    def __init__(self, reply: str = "已根据真实地图结果更新地点。") -> None:
        self.reply = reply
        self.calls: list[object] = []

    def generate(self, result, clarification=None):
        self.calls.append((result, clarification))
        return self.reply


class FakeUpdater:
    def __init__(self, state: TripState) -> None:
        self.state = state
        self.executed: list[object] = []

    def read_current_state(self, session, trip_id):
        return self.state

    def read_memory_context(self, session, trip_id):
        return [{"category": "preference", "key": "pace", "value": {"text": "慢节奏"}}]

    def execute_decision(self, session, trip_id, state, decision, **kwargs):
        self.executed.append((trip_id, state, decision, kwargs))
        updated = state.model_copy(update={"revision": state.revision + 1})
        return TripStateUpdateResult(updated, [], assess_trip_state(updated), executed_tools=True)


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


def test_direct_question_never_executes_a_travel_tool() -> None:
    state = TripState(trip_id=uuid4(), revision=2, destination={"query": "南京"})
    planner = FakePlanner(AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        assistant_message="南京可以先看看中山陵和玄武湖。",
    ))
    manager = TravelManagerAgent(planner, FakeReplyGenerator())
    updater = FakeUpdater(state)
    session = FakeSession()

    result = TripStateConversationService(updater, TripStateClarification(), manager_agent=manager).handle(
        session, state.trip_id, "有什么推荐？", expected_revision=2,
        conversation_context=[{"role": "user", "content": "我想去南京"}],
    )

    assert result.assistant_message == "南京可以先看看中山陵和玄武湖。"
    assert result.clarification.questions == []
    assert updater.executed == []
    assert planner.calls[0][3] == [{"role": "user", "content": "我想去南京"}]
    assert session.commit_calls == 1


def test_state_change_runs_validated_tools_then_same_agent_writes_reply() -> None:
    state = TripState(trip_id=uuid4(), revision=4, destination={"query": "南京"})
    planner = FakePlanner(AgentDecision(patch=TripStatePatch(accommodation={"query": "金陵饭店"})))
    reply_generator = FakeReplyGenerator()
    manager = TravelManagerAgent(planner, reply_generator)
    updater = FakeUpdater(state)
    session = FakeSession()

    result = TripStateConversationService(updater, TripStateClarification(), manager_agent=manager).handle(
        session, state.trip_id, "住金陵饭店", expected_revision=4
    )

    assert result.state.revision == 5
    assert result.assistant_message == "已根据真实地图结果更新地点。"
    assert len(updater.executed) == 1
    assert updater.executed[0][3]["refresh_empty"] is False
    assert reply_generator.calls[0][1] is None
    assert session.commit_calls == 1


def test_invalid_agent_step_falls_back_without_executing_tools() -> None:
    state = TripState(trip_id=uuid4(), revision=1)
    updater = FakeUpdater(state)
    result = TripStateConversationService(
        updater, TripStateClarification(), manager_agent=TravelManagerAgent(FailingPlanner(), FakeReplyGenerator())
    ).handle(FakeSession(), state.trip_id, "帮我修改行程", expected_revision=1)

    assert result.assistant_message is not None
    assert updater.executed == []
