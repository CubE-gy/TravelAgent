from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.trip import TripCreate, TripUpdate


def test_trip_create_normalizes_name() -> None:
    trip = TripCreate(
        name="  北京五日游  ",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
    )

    assert trip.name == "北京五日游"


@pytest.mark.parametrize("name", ["", "   "])
def test_trip_create_rejects_blank_name(name: str) -> None:
    with pytest.raises(ValidationError):
        TripCreate(
            name=name,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 5),
        )


def test_trip_create_rejects_invalid_date_range() -> None:
    with pytest.raises(ValidationError, match="start_date must not be after end_date"):
        TripCreate(
            name="北京五日游",
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 1),
        )


def test_trip_update_requires_at_least_one_field() -> None:
    with pytest.raises(ValidationError, match="at least one field must be provided"):
        TripUpdate()


def test_trip_update_normalizes_name() -> None:
    trip_update = TripUpdate(name="  更新后的旅行  ")

    assert trip_update.name == "更新后的旅行"


@pytest.mark.parametrize("field_name", ["name", "start_date", "end_date"])
def test_trip_update_rejects_explicit_null(field_name: str) -> None:
    with pytest.raises(ValidationError, match=f"{field_name} must not be null"):
        TripUpdate(**{field_name: None})
