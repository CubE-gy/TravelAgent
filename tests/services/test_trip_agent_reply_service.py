from uuid import uuid4

from app.schemas.trip_state import TripState
from app.services.trip_state_assessor import assess_trip_state
from app.schemas.trip_state_clarification import TripStateClarification
from app.services.llm_provider import MockLlmProvider
from app.services.trip_agent_reply_service import AgentFinalReply, TripAgentReplyService
from app.services.trip_state_update_service import TripStateUpdateResult


def test_reply_is_generated_from_executed_tool_facts() -> None:
    provider = MockLlmProvider({"message": "已把中山陵加入行程，并在地图上标记。"})
    result = TripStateUpdateResult(
        state=TripState(trip_id=uuid4(), destination={"query": "南京"}),
        location_failures=[],
        assessment=assess_trip_state(TripState(trip_id=uuid4(), destination={"query": "南京"})),
        executed_tools=True,
    )

    message = TripAgentReplyService(provider).generate(result, TripStateClarification())

    assert message.startswith("已把中山陵")
    assert provider.calls[0][1] is AgentFinalReply
    assert "Executed travel tool results JSON" in provider.calls[0][0][1].content


def test_reply_falls_back_when_the_second_llm_turn_fails() -> None:
    state = TripState(trip_id=uuid4(), destination={"query": "南京"})
    result = TripStateUpdateResult(
        state=state,
        location_failures=[],
        assessment=assess_trip_state(state),
        executed_tools=True,
    )

    message = TripAgentReplyService(MockLlmProvider()).generate(result, TripStateClarification())

    assert message == "已处理本次旅行信息。你可以继续补充地点、酒店、交通或偏好。"
