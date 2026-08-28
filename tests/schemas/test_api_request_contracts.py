"""Contract tests for strict client-input schemas."""

from collections.abc import Callable
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import IntercityTravelMode
from app.schemas.trip import TripCreate, TripUpdate
from app.schemas.trip_conversation import TripMessageCreate
from app.schemas.trip_location_confirmation import TripLocationConfirmationCreate
from app.schemas.trip_public_transport_plan import (
    DailyPlacePlan,
    IntercityPublicTransportLeg,
    PublicTransportPlanningRequest,
    UserConfirmedIntercityTransportFact,
)


def _intercity_leg() -> dict[str, object]:
    return {
        "travel_mode": IntercityTravelMode.HIGH_SPEED_RAIL,
        "departure_poi_id": "NANJING_SOUTH",
        "arrival_poi_id": "BEIJING_SOUTH",
        "fact": {"service_identifier": "G1", "duration_seconds": 60},
    }


@pytest.mark.parametrize(
    "create_request",
    [
        lambda: TripCreate(name="北京游", start_date="2026-10-01", end_date="2026-10-02", typo=True),
        lambda: TripUpdate(name="北京游", typo=True),
        lambda: TripMessageCreate(message="去北京", typo=True),
        lambda: TripLocationConfirmationCreate(field="destination", poi_id="POI_1", typo=True),
        lambda: DailyPlacePlan(day_number=1, place_poi_ids=["POI_1"], typo=True),
        lambda: IntercityPublicTransportLeg(**_intercity_leg(), typo=True),
        lambda: UserConfirmedIntercityTransportFact(service_identifier="G1", duration_seconds=60, typo=True),
        lambda: PublicTransportPlanningRequest(
            trip_id=uuid4(),
            outbound_intercity=_intercity_leg(),
            return_intercity=_intercity_leg(),
            daily_places=[{"day_number": 1, "place_poi_ids": ["POI_1"]}],
            typo=True,
        ),
    ],
)
def test_api_request_models_reject_unknown_fields(create_request: Callable[[], object]) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        create_request()


def test_public_transport_request_rejects_unknown_nested_input() -> None:
    outbound_intercity = _intercity_leg()
    outbound_intercity["fact"] = {
        "service_identifier": "G1",
        "duration_seconds": 60,
        "typo": True,
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PublicTransportPlanningRequest(
            trip_id=uuid4(),
            outbound_intercity=outbound_intercity,
            return_intercity=_intercity_leg(),
            daily_places=[{"day_number": 1, "place_poi_ids": ["POI_1"]}],
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TripMessageCreate(message="去北京"),
        lambda: TripLocationConfirmationCreate(field="destination", poi_id="POI_1"),
    ],
)
def test_existing_state_write_requests_require_expected_revision(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError, match="expected_revision"):
        factory()
