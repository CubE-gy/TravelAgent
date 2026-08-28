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
    LocationConfirmationIntent,
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
    assert "Do not invent missing information" in messages[0].content
    assert "城际坐高铁/火车/飞机/自驾" in messages[0].content
    assert "返回原地”" in messages[0].content
    assert '"accommodation":{"query":"王府井附近"' in messages[1].content
    assert messages[1].content.endswith("User message:\n酒店改到国贸附近")


def test_extract_returns_empty_patch_when_provider_finds_no_explicit_change() -> None:
    provider = FakePatchProvider(TripStateMessageUnderstanding())
    service = TripStateExtractionService(provider)

    understanding = service.extract(TripState(trip_id=uuid4()), "你好")

    assert understanding.patch.model_fields_set == set()
    assert understanding.location_confirmation is None


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
    assert '"poi_id":"B1"' in provider.calls[0][0][1].content


def test_extract_rejects_blank_user_message_without_calling_provider() -> None:
    provider = FakePatchProvider(TripStateMessageUnderstanding())
    service = TripStateExtractionService(provider)

    with pytest.raises(ValueError, match="user_message must not be blank"):
        service.extract(TripState(trip_id=uuid4()), "   ")

    assert provider.calls == []
