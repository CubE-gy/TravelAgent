from uuid import uuid4

from app.schemas.map import ResolvedLocation
from app.schemas.trip_recommendation import TripRecommendationRead
from app.schemas.trip_state import TripState, TripStatePatch
from app.schemas.trip_state_clarification import TripStateClarification
from app.services.travel_manager_agent import TravelManagerAgent, TravelManagerTool
from app.services.travel_tool import (
    SearchRecommendationsArgs,
    ToolContext,
    ToolObservation,
    TravelTool,
    UpdateTripStateArgs,
    UpdateTripStateTool,
    SearchRecommendationsTool,
)
from app.services.travel_tool_registry import TravelToolRegistry
from app.services.trip_state_assessor import assess_trip_state
from app.services.trip_state_conversation_service import TripStateConversationService
from app.services.trip_state_extraction_service import AgentDecision, TripStateMessageIntent
from app.services.trip_state_update_service import TripStateUpdateResult
from app.services.llm_provider import LlmResponseError


class FakePlanner:
    def __init__(self, decision: AgentDecision) -> None:
        self.decision = decision
        self.calls: list[tuple[TripState, str, list[dict[str, object]], list[dict[str, str]] | None, list[dict[str, object]] | None]] = []

    def extract(self, state, message, memories=None, conversation_context=None, turn_facts=None, recommendation_context=None):
        self.calls.append((state, message, memories or [], conversation_context, turn_facts))
        return self.decision


class FailingPlanner:
    def extract(self, *args, **kwargs):
        raise LlmResponseError("invalid response")


class FakeReplyGenerator:
    def __init__(self, reply: str = "已根据真实地图结果更新地点。") -> None:
        self.reply = reply
        self.calls: list[tuple[object, object | None]] = []

    def generate(self, observation, *, current_state, user_message=None, conversation_context=None, turn_facts=None, clarification=None):
        self.calls.append((observation, clarification))
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


def _update_tool_registry(updater: FakeUpdater) -> TravelToolRegistry:
    return TravelToolRegistry([UpdateTripStateTool(updater)])  # type: ignore[arg-type]


def test_direct_question_never_executes_a_travel_tool() -> None:
    state = TripState(trip_id=uuid4(), revision=2, destination={"query": "南京"})
    planner = FakePlanner(AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        assistant_message="南京可以先看看中山陵和玄武湖。",
    ))
    manager = TravelManagerAgent(planner, FakeReplyGenerator(), _update_tool_registry(FakeUpdater(state)))
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
    updater = FakeUpdater(state)
    reply_generator = FakeReplyGenerator()
    manager = TravelManagerAgent(planner, reply_generator, _update_tool_registry(updater))
    session = FakeSession()

    result = TripStateConversationService(updater, TripStateClarification(), manager_agent=manager).handle(
        session, state.trip_id, "住金陵饭店", expected_revision=4
    )

    assert result.state.revision == 5
    assert result.assistant_message == "已根据真实地图结果更新地点。"
    assert len(updater.executed) == 1
    assert updater.executed[0][3]["commit"] is False
    assert reply_generator.calls[0][1] is None
    assert reply_generator.calls[0][0].summary.startswith("update_trip_state")
    assert session.commit_calls == 1


def test_invalid_agent_step_falls_back_without_executing_tools() -> None:
    state = TripState(trip_id=uuid4(), revision=1)
    updater = FakeUpdater(state)
    result = TripStateConversationService(
        updater, TripStateClarification(),
        manager_agent=TravelManagerAgent(FailingPlanner(), FakeReplyGenerator(), _update_tool_registry(updater)),
    ).handle(FakeSession(), state.trip_id, "帮我修改行程", expected_revision=1)

    assert result.assistant_message is not None
    assert updater.executed == []
    assert "本次没有修改行程" in result.assistant_message


def test_search_tool_observation_drives_the_reply() -> None:
    class StubSearchTool:
        name = "search_recommendations"
        description = "stub"
        def __init__(self) -> None:
            self.calls: list[tuple[SearchRecommendationsArgs, ToolContext]] = []
            self.candidates = [
                TripRecommendationRead(
                    kind="accommodation",
                    location=ResolvedLocation(
                        poi_id="B1", name="金陵饭店", address="中山路1号", category_name="酒店",
                        coordinate={"latitude": 32.04, "longitude": 118.78},
                    ),
                )
            ]
        def extract_args(self, decision: AgentDecision) -> SearchRecommendationsArgs:
            return SearchRecommendationsArgs(
                kind=decision.recommendation_kind or "accommodation",
                query=decision.recommendation_query,
            )
        def run(self, args, context):
            self.calls.append((args, context))
            return ToolObservation(
                summary="search_recommendations: accommodation returned 1 candidates",
                data={
                    "kind": args.kind, "query": args.query, "session_id": str(uuid4()),
                    "candidates": [
                        {"poi_id": c.location.poi_id, "name": c.location.name,
                         "address": c.location.address, "category": c.location.category_name}
                        for c in self.candidates
                    ],
                },
            )

    state = TripState(trip_id=uuid4(), revision=1)
    updater = FakeUpdater(state)
    planner = FakePlanner(AgentDecision(
        intent="conversation", recommendation_kind="accommodation", assistant_message=None,
    ))
    reply_generator = FakeReplyGenerator(reply="金陵饭店在新街口，可直接选择。")
    search_tool = StubSearchTool()
    registry = TravelToolRegistry([search_tool])  # type: ignore[list-item]
    manager = TravelManagerAgent(planner, reply_generator, registry)
    session = FakeSession()

    result = TripStateConversationService(updater, TripStateClarification(), manager_agent=manager).handle(
        session, state.trip_id, "找新街口附近酒店", expected_revision=1,
    )

    assert search_tool.calls, "search tool should have been invoked"
    assert result.assistant_message == "金陵饭店在新街口，可直接选择。"
    assert len(result.recommendations) == 1
    assert updater.executed == []
    assert session.commit_calls == 1


def test_unknown_tool_in_decision_raises_when_run() -> None:
    from app.services.travel_tool_registry import UnknownTravelToolError
    state = TripState(trip_id=uuid4(), revision=1)
    planner = FakePlanner(AgentDecision(patch=TripStatePatch(destination={"query": "南京"})))
    registry = TravelToolRegistry([])  # no tools registered
    manager = TravelManagerAgent(planner, FakeReplyGenerator(), registry)
    session = FakeSession()
    turn = manager.decide(
        state, "去南京", trip_memories=[],
    )

    with __import__("pytest").raises(UnknownTravelToolError):
        manager.run_tool(turn, ToolContext(session=session, trip_id=state.trip_id, current_state=state, expected_revision=1))


def test_tool_decision_dispatches_through_the_registry() -> None:
    """UpdateTripStateTool sees the validated decision and returns an observation."""
    state = TripState(trip_id=uuid4(), revision=1)
    decision = AgentDecision(patch=TripStatePatch(destination={"query": "南京"}), tool_name="update_trip_state")
    updater = FakeUpdater(state)
    registry = TravelToolRegistry([UpdateTripStateTool(updater)])  # type: ignore[arg-type]
    manager = TravelManagerAgent(FakePlanner(decision), FakeReplyGenerator(), registry)
    turn = manager.decide(state, "去南京", trip_memories=[])

    observation = manager.run_tool(
        turn, ToolContext(session=FakeSession(), trip_id=state.trip_id, current_state=state, expected_revision=1),
    )

    assert observation.summary.startswith("update_trip_state")
    assert observation.data["executed_operations"] == ["apply_patch"]
    assert observation.data["state_revision"] == 2


def test_run_tool_refuses_turns_without_a_tool() -> None:
    state = TripState(trip_id=uuid4(), revision=1)
    decision = AgentDecision(intent="conversation", assistant_message="好的。")
    updater = FakeUpdater(state)
    manager = TravelManagerAgent(FakePlanner(decision), FakeReplyGenerator(), _update_tool_registry(updater))
    turn = manager.decide(state, "继续", trip_memories=[])

    with __import__("pytest").raises(ValueError):
        manager.run_tool(
            turn, ToolContext(session=FakeSession(), trip_id=state.trip_id, current_state=state, expected_revision=1),
        )
