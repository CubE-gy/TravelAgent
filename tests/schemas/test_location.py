import pytest
from pydantic import ValidationError

from app.schemas.location import Location


def test_location_accepts_name_and_optional_address() -> None:
    location = Location(name="  北京首都国际机场  ", address="  北京市顺义区  ")

    assert location.name == "北京首都国际机场"
    assert location.address == "北京市顺义区"
    assert location.latitude is None
    assert location.longitude is None


def test_location_accepts_complete_coordinates() -> None:
    location = Location(name="天安门", latitude=39.9087, longitude=116.3975)

    assert location.model_dump() == {
        "name": "天安门",
        "address": None,
        "latitude": 39.9087,
        "longitude": 116.3975,
    }


@pytest.mark.parametrize(
    "location_data",
    [
        {"name": "天安门", "latitude": 39.9087},
        {"name": "天安门", "longitude": 116.3975},
        {"name": "天安门", "latitude": 91, "longitude": 116.3975},
        {"name": "天安门", "latitude": 39.9087, "longitude": 181},
    ],
)
def test_location_rejects_incomplete_or_out_of_range_coordinates(
    location_data: dict[str, str | float]
) -> None:
    with pytest.raises(ValidationError):
        Location(**location_data)
