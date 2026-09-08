from uuid import uuid4

import pytest

from app.schemas.trip_state import TripState, TripStateLocationField, TripStatePatch
from app.schemas.trip_state_operation import (
    TripStateLocationConfirmationOperation,
    TripStateOperationKind,
    TripStatePatchOperation,
)
from app.services.llm_provider import LlmMessage, LlmProvider
from app.services.trip_state_extraction_service import (
    AgentDecision,
    AgentScope,
    LocationConfirmationIntent,
    TripStateMessageIntent,
    TripStatePatchField,
    TripStateExtractionService,
    TripStateMessageUnderstanding,
)


class FakePatchProvider:
    def __init__(self, result: TripStateMessageUnderstanding) -> None:
        self.result = result
        self.calls: list[tuple[list[LlmMessage], type[TripStateMessageUnderstanding]]] = []

    def generate_structured(
        self,
        messages: list[LlmMessage],
        response_model: type[TripStateMessageUnderstanding],
    ) -> TripStateMessageUnderstanding:
        self.calls.append((messages, response_model))
        return self.result


class SequentialPatchProvider:
    def __init__(self, results: list[TripStateMessageUnderstanding]) -> None:
        self._results = iter(results)
        self.calls: list[tuple[list[LlmMessage], type[TripStateMessageUnderstanding]]] = []

    def generate_structured(
        self,
        messages: list[LlmMessage],
        response_model: type[TripStateMessageUnderstanding],
    ) -> TripStateMessageUnderstanding:
        self.calls.append((messages, response_model))
        return next(self._results)


def test_extract_sends_current_state_and_user_message_to_provider() -> None:
    current_state = TripState(
        trip_id=uuid4(),
        destination={"query": "北京"},
        accommodation={"query": "王府井附近"},
    )
    expected = TripStateMessageUnderstanding(
        patch=TripStatePatch(accommodation={"query": "国贸附近"})
    )
    provider = FakePatchProvider(expected)
    service = TripStateExtractionService(provider)

    understanding = service.extract(current_state, "  酒店改到国贸附近  ")

    assert isinstance(provider, LlmProvider)
    assert understanding == expected
    assert len(provider.calls) == 1
    messages, response_model = provider.calls[0]
    assert response_model is TripStateMessageUnderstanding
    assert response_model is AgentDecision
    assert "Do not invent missing information" in messages[0].content
    assert "城际坐高铁/火车/汽车/飞机/自驾" in messages[0].content
    assert "返回原地”" in messages[0].content
    assert '"accommodation":{"query":"王府井附近"' in messages[0].content
    assert messages[-1].role.value == "user"
    assert messages[-1].content == "酒店改到国贸附近"
    assert "酒店改到国贸附近" not in messages[0].content


def test_extract_includes_current_trip_memories_as_context() -> None:
    provider = FakePatchProvider(TripStateMessageUnderstanding())

    TripStateExtractionService(provider).extract(
        TripState(trip_id=uuid4()),
        "酒店要安静一些",
        [{"category": "preference", "key": "hotel", "value": {"text": "安静"}}],
    )

    assert '"category":"preference"' in provider.calls[0][0][0].content
    assert '"text":"安静"' in provider.calls[0][0][0].content


def test_extract_includes_pending_recommendations_as_reference_context() -> None:
    provider = FakePatchProvider(TripStateMessageUnderstanding(
        intent=TripStateMessageIntent.CONVERSATION,
        assistant_message="我会按更高档的条件重新查找。",
        recommendation_kind="accommodation",
        recommendation_query="高档酒店",
    ))

    TripStateExtractionService(provider).extract(
        TripState(trip_id=uuid4(), destination={"query": "南京"}), "档次高一些",
        recommendation_context={"kind": "accommodation", "recommendations": [{"kind": "accommodation", "location": {"poi_id": "hotel-1", "name": "普通酒店", "coordinate": {"latitude": 32.0, "longitude": 118.0}}}]},
    )

    assert '"kind":"accommodation"' in provider.calls[0][0][0].content
    assert '"name":"普通酒店"' in provider.calls[0][0][0].content


def test_extract_returns_empty_patch_when_provider_finds_no_explicit_change() -> None:
    provider = FakePatchProvider(TripStateMessageUnderstanding())
    service = TripStateExtractionService(provider)

    understanding = service.extract(TripState(trip_id=uuid4()), "你好")

    assert understanding.patch.model_fields_set == set()
    assert understanding.location_confirmation is None


def test_extract_keeps_a_conversational_llm_reply_out_of_trip_state_operations() -> None:
    provider = FakePatchProvider(
        TripStateMessageUnderstanding(
            intent=TripStateMessageIntent.CONVERSATION,
            assistant_message="南京可以考虑中山陵、玄武湖等地点；如果你选中一个，我可以把它放到地图上。",
        )
    )

    understanding = TripStateExtractionService(provider).extract(
        TripState(trip_id=uuid4(), destination={"query": "南京"}), "还有什么推荐地方？"
    )

    assert understanding.intent is TripStateMessageIntent.CONVERSATION
    assert understanding.scope is AgentScope.TRAVEL
    assert understanding.operations() == ()
    assert len(provider.calls) == 1


def test_out_of_scope_decision_is_never_routed_to_travel_tools() -> None:
    decision = TripStateMessageUnderstanding(
        intent=TripStateMessageIntent.OUT_OF_SCOPE,
        assistant_message="我可以继续帮你处理这趟旅行的地点、住宿或交通。",
    )

    assert decision.scope is AgentScope.OUT_OF_SCOPE
    assert decision.operations() == ()
    assert decision.tool_calls == ()


def test_understanding_exposes_explicit_operations_in_deterministic_order() -> None:
    understanding = TripStateMessageUnderstanding(
        patch=TripStatePatch(accommodation={"query": "国贸附近"}),
        location_confirmation=LocationConfirmationIntent(
            field=TripStateLocationField.DESTINATION,
            selected_poi_id="B1",
        ),
    )

    operations = understanding.operations()

    assert len(operations) == 2
    assert isinstance(operations[0], TripStatePatchOperation)
    assert operations[0].kind is TripStateOperationKind.APPLY_PATCH
    assert operations[0].patch.accommodation is not None
    assert isinstance(operations[1], TripStateLocationConfirmationOperation)
    assert operations[1].kind is TripStateOperationKind.CONFIRM_LOCATION
    assert operations[1].selected_poi_id == "B1"


def test_extract_retries_when_explicit_trip_information_was_omitted() -> None:
    provider = SequentialPatchProvider(
        [
            TripStateMessageUnderstanding(),
            TripStateMessageUnderstanding(patch=TripStatePatch(destination={"query": "北京"})),
        ]
    )

    understanding = TripStateExtractionService(provider).extract(
        TripState(trip_id=uuid4()), "我要去北京"
    )

    assert understanding.patch.destination is not None
    assert understanding.patch.destination.query == "北京"
    assert len(provider.calls) == 2
    assert "previous extraction produced an empty patch" in provider.calls[1][0][0].content


def test_strict_schema_nulls_do_not_clear_state_without_cleared_fields() -> None:
    strict_patch = TripStatePatch().model_dump()

    understanding = TripStateMessageUnderstanding.model_validate(
        {"patch": strict_patch, "cleared_fields": []}
    )

    assert understanding.patch.model_fields_set == set()


def test_strict_schema_uses_cleared_fields_for_explicit_removals() -> None:
    strict_patch = TripStatePatch().model_dump()

    understanding = TripStateMessageUnderstanding.model_validate(
        {
            "patch": strict_patch,
            "cleared_fields": [TripStatePatchField.ACCOMMODATION],
        }
    )

    assert understanding.patch.model_fields_set == {"accommodation"}
    assert understanding.patch.accommodation is None


def test_partial_patch_keeps_separately_declared_clears() -> None:
    understanding = TripStateMessageUnderstanding(
        patch=TripStatePatch(destination={"query": "上海"}),
        cleared_fields=[TripStatePatchField.ACCOMMODATION],
    )

    operations = understanding.operations()

    assert len(operations) == 1
    assert isinstance(operations[0], TripStatePatchOperation)
    assert operations[0].patch.model_fields_set == {"destination", "accommodation"}
    assert operations[0].patch.destination is not None
    assert operations[0].patch.accommodation is None


def test_extract_does_not_replace_an_empty_llm_result_with_rule_based_facts() -> None:
    provider = SequentialPatchProvider(
        [TripStateMessageUnderstanding(), TripStateMessageUnderstanding()]
    )

    understanding = TripStateExtractionService(provider).extract(
        TripState(trip_id=uuid4()),
        "我从南京新街口出发，2026年10月1日去北京，10月3日回南京新街口，"
        "城际坐高铁，当地坐公共交通，住王府井附近，想去故宫。",
    )

    assert understanding.patch.model_fields_set == set()
    assert len(provider.calls) == 2


def test_extract_returns_only_an_existing_candidate_confirmation_intent() -> None:
    current_state = TripState(
        trip_id=uuid4(),
        destination={
            "query": "万达广场",
            "resolution_status": "ambiguous",
            "candidates": [
                {"poi_id": "B1", "name": "北京万达", "coordinate": {"latitude": 39.9, "longitude": 116.4}},
                {"poi_id": "B2", "name": "上海万达", "coordinate": {"latitude": 31.2, "longitude": 121.5}},
            ],
        },
    )
    expected = TripStateMessageUnderstanding(
        location_confirmation=LocationConfirmationIntent(
            field=TripStateLocationField.DESTINATION,
            selected_poi_id="B1",
        )
    )
    provider = FakePatchProvider(expected)

    understanding = TripStateExtractionService(provider).extract(current_state, "选北京那个")

    assert understanding.patch.model_fields_set == set()
    assert understanding.location_confirmation == expected.location_confirmation
    assert '"poi_id":"B1"' in provider.calls[0][0][0].content


def test_extract_rejects_blank_user_message_without_calling_provider() -> None:
    provider = FakePatchProvider(TripStateMessageUnderstanding())
    service = TripStateExtractionService(provider)

    with pytest.raises(ValueError, match="user_message must not be blank"):
        service.extract(TripState(trip_id=uuid4()), "   ")

    assert provider.calls == []


def test_extract_forwards_structured_turn_facts_into_the_instruction_layer() -> None:
    provider = SequentialPatchProvider([AgentDecision(intent="conversation", assistant_message="ok")])
    state = TripState(trip_id=uuid4())
    turn_facts = [{
        "turn_index": 1, "user_message": "去南京",
        "decision": "update_trip_state", "operations": ["apply_patch"],
        "location_failures": ["places/火星博物馆"], "recommendation_count": 0,
    }]

    TripStateExtractionService(provider).extract(
        state, "再加个酒店", turn_facts=turn_facts,
    )

    system = provider.calls[0][0][0].content
    assert "最近几轮已执行的操作" in system
    assert "解析失败 places/火星博物馆" in system
