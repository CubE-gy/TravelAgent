import pytest
from pydantic import BaseModel, ValidationError

from app.models.enums import TravelMode


class TravelModePayload(BaseModel):
    travel_mode: TravelMode


@pytest.mark.parametrize(
    ("travel_mode", "expected_value"),
    [
        (TravelMode.PUBLIC_TRANSPORT, "public_transport"),
        (TravelMode.DRIVING, "driving"),
    ],
)
def test_travel_mode_has_stable_api_values(
    travel_mode: TravelMode, expected_value: str
) -> None:
    assert travel_mode.value == expected_value
    assert TravelModePayload(travel_mode=travel_mode).model_dump(mode="json") == {
        "travel_mode": expected_value
    }


def test_travel_mode_rejects_unsupported_value() -> None:
    with pytest.raises(ValidationError):
        TravelModePayload(travel_mode="walking")
