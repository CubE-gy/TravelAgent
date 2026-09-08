"""Opt-in real-model decisions: no map calls and no database writes."""

from uuid import uuid4

import pytest

from app.core.config import Settings
from app.schemas.trip_state import TripState
from app.services.llm_provider_factory import create_llm_provider
from app.services.trip_state_extraction_service import TripStateExtractionService
from tests.services.test_real_llm_smoke import _is_real_llm_smoke_configured


CASES = [
    ("hotel_short_answer", "杭州", "酒店，西湖边上", [
        ("user", "给我推荐一些"),
        ("assistant", "你想找住宿还是游玩的景点？"),
    ], "search_recommendations", "accommodation"),
    ("place_short_answer", "成都", "景点吧", [
        ("user", "附近有合适的吗"),
        ("assistant", "你想找酒店，还是附近可游玩的地方？"),
    ], "search_recommendations", "places"),
    ("hotel_reference", "苏州", "帮我找几家吧", [
        ("user", "我想住平江路附近"),
        ("assistant", "可以，我可以帮你找这一区域的酒店。"),
    ], "search_recommendations", "accommodation"),
    ("switch_to_change", "南京", "不找了，我住金陵饭店", [
        ("user", "推荐酒店"),
        ("assistant", "希望在哪个区域找？"),
    ], "update_trip_state", None),
    ("cancel", "杭州", "先不推荐了", [
        ("user", "推荐酒店"),
        ("assistant", "想住哪个区域？"),
    ], "final_response", None),
    ("switch_topic", "北京", "先不找酒店，帮我总结现在的行程", [
        ("user", "推荐酒店"),
        ("assistant", "想住哪个区域？"),
    ], "final_response", None),
    ("unrelated", "成都", "帮我证明勾股定理", [
        ("user", "推荐景点"), ("assistant", "喜欢什么类型？"),
    ], "final_response", None),
    ("explicit_change", "北京", "酒店改到国贸附近", [], "update_trip_state", None),
]


@pytest.mark.llm_smoke
@pytest.mark.parametrize("case,city,message,history,tool,kind", CASES,
                         ids=[item[0] for item in CASES])
def test_real_model_resolves_dialogue_without_case_specific_prompt(
    case, city, message, history, tool, kind,
):
    settings = Settings()
    if not _is_real_llm_smoke_configured(settings):
        pytest.skip("real model credentials are not configured")
    decision = TripStateExtractionService(create_llm_provider(settings)).extract(
        TripState(trip_id=uuid4(), destination={"query": city}),
        message, conversation_context=[{"role": role, "content": text} for role, text in history],
    )
    assert decision.tool_name == tool
    assert decision.recommendation_kind == kind
    if tool != "update_trip_state":
        assert decision.operations() == ()
        assert decision.memory_instructions == []
        if tool == "final_response":
            assert decision.assistant_message and decision.assistant_message.strip()
    else:
        assert decision.patch.accommodation is not None
        assert decision.patch.model_fields_set == {"accommodation"}
        assert decision.patch.accommodation.query == (
            "金陵饭店" if case == "switch_to_change" else "国贸附近"
        )
