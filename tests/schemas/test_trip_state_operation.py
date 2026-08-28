import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.trip_state import TripStateLocationField, TripStatePatch
from app.schemas.trip_state_operation import (
    TripStateLocationConfirmationOperation,
    TripStateOperation,
    TripStateOperationKind,
    TripStatePatchOperation,
)


def test_operation_models_reject_a_kind_owned_by_another_operation() -> None:
    with pytest.raises(ValidationError):
        TripStatePatchOperation(
            kind=TripStateOperationKind.CONFIRM_LOCATION,
            patch=TripStatePatch(destination={"query": "上海"}),
        )


def test_discriminated_operation_union_selects_the_matching_model() -> None:
    operation = TypeAdapter(TripStateOperation).validate_python(
        {
            "kind": "confirm_location",
            "field": "places",
            "selected_poi_id": "  B0001  ",
            "place_index": 0,
        }
    )

    assert isinstance(operation, TripStateLocationConfirmationOperation)
    assert operation.selected_poi_id == "B0001"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "kind": "confirm_location",
            "field": TripStateLocationField.PLACES,
            "selected_poi_id": "B0001",
        },
        {
            "kind": "confirm_location",
            "field": TripStateLocationField.DESTINATION,
            "selected_poi_id": "B0001",
            "place_index": 0,
        },
        {
            "kind": "confirm_location",
            "field": TripStateLocationField.DESTINATION,
            "selected_poi_id": "   ",
        },
    ],
)
def test_location_confirmation_operation_rejects_invalid_domain_inputs(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(TripStateOperation).validate_python(payload)
