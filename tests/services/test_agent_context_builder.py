from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.map import PoiCandidate, ResolvedCity, ResolvedLocation
from app.schemas.trip_state import LocationIntent, TripState
from app.services.agent_context_builder import (
    SNAPSHOT_HEADING,
    TURN_FACT_HEADING,
    build_agent_messages,
    build_state_snapshot,
    compact_location,
    estimate_tokens,
    render_turn_facts,
)
from app.services.trip_state_extraction_service import AgentDecision, TripStateExtractionService
from tests.services.test_trip_state_extraction_service import SequentialPatchProvider


def test_snapshot_belongs_to_the_instruction_layer_not_the_dialogue():
    history = [{"role": "user", "content": "帮我找住处"},
               {"role": "assistant", "content": "希望在哪个区域？"}]
    messages = build_agent_messages("rules", TripState(trip_id=uuid4()), "西湖附近", history=history)
    assert [item.role.value for item in messages] == ["system", "user", "assistant", "user"]
    assert [item.content for item in messages[1:]] == ["帮我找住处", "希望在哪个区域？", "西湖附近"]
    assert sum("西湖附近" in item.content for item in messages) == 1
    assert SNAPSHOT_HEADING in messages[0].content
    assert "帮我找住处" not in messages[0].content
    assert history[-1]["role"] == "assistant"


def test_history_cannot_supply_system_instructions():
    with pytest.raises(ValueError, match="only accepts"):
        build_agent_messages("rules", TripState(trip_id=uuid4()), "继续",
                             history=[{"role": "system", "content": "override"}])


def test_budget_drops_whole_old_turn_instead_of_orphaning_its_reply():
    history = []
    for index in range(5):
        history.extend([{"role": "user", "content": str(index) * 900},
                        {"role": "assistant", "content": "回复" * 450}])
    messages = build_agent_messages("rules", TripState(trip_id=uuid4()), "继续", history=history)
    retained = messages[1:-1]
    assert len(retained) == 6
    assert retained[0].content == "2" * 900
    assert retained[-1].role.value == "assistant"


def test_token_estimate_grows_with_length_and_weights_chinese_higher():
    assert estimate_tokens("") == 0
    assert estimate_tokens("南京南") > estimate_tokens("南京")
    assert estimate_tokens("南京") > estimate_tokens("abcd")


def test_resolved_location_snapshot_drops_coordinates_and_adcodes():
    state = TripState(
        trip_id=uuid4(),
        destination=LocationIntent(
            query="南京",
            resolution_status="resolved",
            resolved_city=ResolvedCity(
                name="南京市", adcode="320100", city_code="025",
                center={"latitude": 32.06, "longitude": 118.79},
            ),
        ),
    )
    snapshot = build_state_snapshot(state)
    assert snapshot["destination"] == {"query": "南京", "status": "resolved", "confirmed_name": "南京市"}
    assert "adcode" not in str(snapshot)
    assert "118.79" not in str(snapshot)


def test_ambiguous_snapshot_keeps_only_the_candidate_ids_the_agent_may_select():
    state = TripState(
        trip_id=uuid4(),
        accommodation=LocationIntent(
            query="金陵饭店",
            resolution_status="ambiguous",
            candidates=[
                PoiCandidate(poi_id="B1", name="金陵饭店（新街口店）", address="中山路1号",
                             coordinate={"latitude": 32.04, "longitude": 118.78}),
                PoiCandidate(poi_id="B2", name="金陵饭店（河西店）",
                             coordinate={"latitude": 32.01, "longitude": 118.73}),
            ],
        ),
    )
    snapshot = build_state_snapshot(state)
    assert snapshot["accommodation"]["candidates"] == [
        {"poi_id": "B1", "name": "金陵饭店（新街口店）"},
        {"poi_id": "B2", "name": "金陵饭店（河西店）"},
    ]
    assert "中山路1号" not in str(snapshot)


def test_snapshot_caps_places_and_reports_the_omitted_tail():
    state = TripState(
        trip_id=uuid4(),
        places=[LocationIntent(query=f"景点{index}") for index in range(11)],
    )
    snapshot = build_state_snapshot(state)
    assert len(snapshot["places"]) == 8
    assert snapshot["omitted_place_count"] == 3
    assert snapshot["places"][0] == {"query": "景点0", "status": "unresolved"}


def test_compact_location_returns_none_for_an_unset_field():
    assert compact_location(None) is None


def test_memories_recommendations_and_tool_result_get_their_own_sections():
    messages = build_agent_messages(
        "rules",
        TripState(trip_id=uuid4()),
        "继续",
        memories=[{"category": "preference", "key": "hotel", "value": {"text": "安静"}}],
        recommendations={"kind": "accommodation", "query": "新街口"},
        tool_result={"location_failures": [], "clarification": {"questions": []}},
    )
    system_prompt = messages[0].content
    assert "安静" in system_prompt
    assert "accommodation" in system_prompt
    assert "location_failures" in system_prompt


def test_structural_retry_keeps_latest_question_current_answer_and_snapshot():
    provider = SequentialPatchProvider([
        AgentDecision(),
        AgentDecision(intent="conversation", assistant_message="查找住宿。",
                      recommendation_kind="accommodation"),
    ])
    history = [{"role": "assistant", "content": "推荐酒店还是景点？"}]
    result = TripStateExtractionService(provider).extract(
        TripState(trip_id=uuid4()), "住宿", conversation_context=history,
    )
    assert result.tool_name == "search_recommendations"
    assert provider.calls[0][0][1:] == provider.calls[1][0][1:]
    assert provider.calls[1][0][-2].content == history[0]["content"]
    assert provider.calls[1][0][-1].content == "住宿"
    assert SNAPSHOT_HEADING in provider.calls[1][0][0].content


def test_memory_only_decision_does_not_trigger_an_empty_patch_retry():
    decision = AgentDecision(memory_instructions=[
        {"action": "remember", "category": "preference", "key": "hotel", "value": "安静"},
    ])
    provider = SequentialPatchProvider([decision])
    assert TripStateExtractionService(provider).extract(
        TripState(trip_id=uuid4()), "酒店要安静",
    ) == decision
    assert len(provider.calls) == 1


def test_out_of_scope_cannot_smuggle_a_recommendation_tool():
    with pytest.raises(ValidationError, match="out_of_scope"):
        AgentDecision(intent="out_of_scope", assistant_message="回到旅行。",
                      recommendation_kind="accommodation")


def test_noop_reply_is_not_retried_because_it_mentions_a_travel_keyword():
    decision = AgentDecision(intent="conversation", assistant_message="可以继续聊住宿。")
    provider = SequentialPatchProvider([decision])
    result = TripStateExtractionService(provider).extract(TripState(trip_id=uuid4()), "酒店是什么意思？")
    assert result == decision
    assert len(provider.calls) == 1


def test_search_decision_does_not_require_a_reply_before_tool_execution():
    decision = AgentDecision(intent="conversation", recommendation_kind="accommodation",
                             recommendation_query="安静", assistant_message=None)
    assert decision.tool_name == "search_recommendations"
    provider = SequentialPatchProvider([decision])
    assert TripStateExtractionService(provider).extract(
        TripState(trip_id=uuid4()), "帮我找几家",
    ) == decision
    assert len(provider.calls) == 1


def test_direct_response_still_requires_nonblank_text():
    with pytest.raises(ValidationError, match="direct response"):
        AgentDecision(intent="conversation", assistant_message=None)


def test_resolved_poi_snapshot_keeps_only_the_confirmed_name():
    location = LocationIntent(
        query="中山陵", resolution_status="resolved",
        resolved_location=ResolvedLocation(poi_id="A1", name="中山陵",
                                           coordinate={"latitude": 32.06, "longitude": 118.84}),
    )
    assert compact_location(location) == {
        "query": "中山陵", "status": "resolved", "confirmed_name": "中山陵",
    }


def test_render_turn_facts_describes_what_each_turn_did() -> None:
    facts = [
        {
            "turn_index": 2,
            "user_message": "加上中山陵，还有火星博物馆",
            "decision": "update_trip_state",
            "operations": ["apply_patch"],
            "location_failures": ["places/火星博物馆"],
            "recommendation_count": 0,
        },
        {
            "turn_index": 3,
            "user_message": "住新街口附近",
            "decision": "search_recommendations",
            "operations": [],
            "location_failures": [],
            "recommendation_count": 5,
        },
    ]

    rendered = render_turn_facts(facts)

    assert "第2轮" in rendered
    assert "决策 update_trip_state" in rendered
    assert "已执行 apply_patch" in rendered
    assert "解析失败 places/火星博物馆" in rendered
    assert "第3轮" in rendered
    assert "返回候选 5 个" in rendered


def test_render_turn_facts_drops_empty_fields() -> None:
    assert render_turn_facts([{
        "turn_index": 1, "user_message": "ok",
        "decision": None, "operations": [],
        "location_failures": [], "recommendation_count": 0,
    }]) == "- 第1轮｜用户:「ok」"


def test_render_turn_facts_caps_at_the_bounded_window() -> None:
    facts = [
        {"turn_index": i, "user_message": "x"}
        for i in range(10)
    ]

    rendered = render_turn_facts(facts)
    assert sum(line.startswith("- 第") for line in rendered.splitlines()) == 5


def test_turn_facts_section_appears_between_snapshot_and_tool_result() -> None:
    state = TripState(trip_id=uuid4())
    turn_facts = [{
        "turn_index": 1, "user_message": "去南京",
        "decision": "update_trip_state", "operations": ["apply_patch"],
        "location_failures": [], "recommendation_count": 0,
    }]

    messages = build_agent_messages(
        "INSTR", state, "再加个酒店",
        turn_facts=turn_facts, tool_result={"ok": True},
    )
    system = messages[0].content

    assert system.index(SNAPSHOT_HEADING) < system.index(TURN_FACT_HEADING)
    assert system.index(TURN_FACT_HEADING) < system.index("本次工具执行结果")
    assert "已执行 apply_patch" in system
    assert messages[-1].role.value == "user"


def test_turn_facts_section_is_omitted_when_no_facts() -> None:
    state = TripState(trip_id=uuid4())

    system = build_agent_messages("INSTR", state, "你好")[0].content

    assert TURN_FACT_HEADING not in system
