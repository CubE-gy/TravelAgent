from uuid import uuid4

from app.schemas.trip_state import TripState
from app.services.trip_state_assessor import assess_trip_state
from app.schemas.trip_state_clarification import TripStateClarification
from app.services.agent_context_builder import TOOL_RESULT_HEADING
from app.services.llm_provider import MockLlmProvider
from app.services.travel_tool import ToolObservation
from app.services.trip_agent_reply_service import AgentFinalReply, TripAgentReplyService
from app.services.trip_state_update_service import TripStateUpdateResult


def _update_observation(state: TripState) -> ToolObservation:
    return ToolObservation(
        summary="update_trip_state: revision 0 -> 1",
        data={"state_revision": 1, "location_failures": [], "executed_operations": ["apply_patch"]},
    )


def test_reply_is_generated_from_executed_tool_facts() -> None:
    provider = MockLlmProvider({"message": "已把中山陵加入行程，并在地图上标记。"})
    state = TripState(trip_id=uuid4(), destination={"query": "南京"})

    message = TripAgentReplyService(provider).generate(_update_observation(state), current_state=state)

    assert message.startswith("已把中山陵")
    assert provider.calls[0][1] is AgentFinalReply
    assert TOOL_RESULT_HEADING in provider.calls[0][0][0].content
    assert '"location_failures":[]' in provider.calls[0][0][0].content


def test_reply_falls_back_when_the_second_llm_turn_fails() -> None:
    state = TripState(trip_id=uuid4(), destination={"query": "南京"})

    message = TripAgentReplyService(MockLlmProvider()).generate(_update_observation(state), current_state=state)

    assert message == "已处理本次旅行信息。你可以继续补充地点、酒店、交通或偏好。"


def test_reply_receives_user_request_and_dialogue_alongside_tool_facts():
    state = TripState(trip_id=uuid4())
    provider = MockLlmProvider({"message": "已处理酒店要求。"})
    TripAgentReplyService(provider).generate(
        _update_observation(state), current_state=state,
        user_message="换成这家",
        conversation_context=[{"role": "assistant", "content": "你希望换酒店吗？"}],
    )
    messages = provider.calls[0][0]
    assert messages[-2].role.value == "assistant"
    assert messages[-2].content == "你希望换酒店吗？"
    assert messages[-1].content == "换成这家"
    assert TOOL_RESULT_HEADING in messages[0].content
    assert '"location_failures":[]' in messages[0].content


def test_reply_failure_preserves_location_failure_in_fallback():
    from app.services.trip_state_location_resolution_service import LocationResolutionFailure

    state = TripState(trip_id=uuid4())
    observation = ToolObservation(
        summary="update_trip_state: revision 0 -> 1",
        data={
            "state_revision": 1,
            "location_failures": [LocationResolutionFailure(
                field="accommodation", query="酒店", error_code="timeout",
            ).__dict__],
            "executed_operations": ["apply_patch"],
        },
    )
    reply = TripAgentReplyService(MockLlmProvider()).generate(observation, current_state=state)
    assert "部分地点查询失败" in reply
    assert "尚未确认地图位置" in reply


def test_reply_falls_back_to_named_candidate_summary_when_search_observation_lacks_llm() -> None:
    state = TripState(trip_id=uuid4())
    observation = ToolObservation(
        summary="search_recommendations: accommodation returned 2 candidates",
        data={
            "kind": "accommodation", "query": "新街口",
            "candidates": [
                {"poi_id": "B1", "name": "金陵饭店", "address": "中山路1号", "category": "酒店"},
                {"poi_id": "B2", "name": "新街口酒店", "address": "中山路5号", "category": "酒店"},
            ],
        },
    )

    reply = TripAgentReplyService(MockLlmProvider()).generate(observation, current_state=state)

    assert "金陵饭店" in reply
    assert "新街口酒店" in reply


def test_reply_forwards_structured_turn_facts_into_the_instruction_layer() -> None:
    provider = MockLlmProvider({"message": "好的。"})
    state = TripState(trip_id=uuid4())
    turn_facts = [{
        "turn_index": 1, "user_message": "去南京",
        "decision": "update_trip_state", "operations": ["apply_patch"],
        "location_failures": [], "recommendation_count": 0,
    }]

    TripAgentReplyService(provider).generate(
        _update_observation(state), current_state=state, turn_facts=turn_facts,
    )

    system = provider.calls[0][0][0].content
    assert "最近几轮已执行的操作" in system
    assert "已执行 apply_patch" in system
