"""Opt-in real Amap evidence for the Stage 3 public-transport planning flow."""

import pytest
from uuid import uuid4

from app.core.config import Settings
from app.models.enums import IntercityTravelMode, TravelMode
from app.schemas.map import ResolvedLocation, Route
from app.schemas.trip_public_transport_plan import (
    PublicTransportPlanningRequest,
    TripRouteFactSource,
    TripRouteLegKind,
)
from app.schemas.trip_state import TripState
from app.services.amap_api_service import AmapApiService
from app.services.map_errors import MapUpstreamError
from app.services.public_transport_trip_planning_service import PublicTransportTripPlanningService


pytestmark = pytest.mark.amap_smoke


def test_real_amap_public_transport_planning_flow() -> None:
    """Build one real door-to-door plan without querying live tickets or saving a plan."""
    settings = Settings()
    if settings.amap_web_api_key is None or not settings.amap_web_api_key.get_secret_value().strip():
        pytest.skip("AMAP_WEB_API_KEY is not configured")

    map_service = RetryingAmapMapService(AmapApiService(settings.amap_web_api_key))
    origin = _search_and_resolve(map_service, "天安门", region="北京")
    accommodation = _search_and_resolve(map_service, "青岛市人民政府", region="青岛")
    place = _search_and_resolve(map_service, "青岛奥帆中心", region="青岛")
    outbound_departure = _search_and_resolve(map_service, "北京南站", region="北京")
    outbound_arrival = _search_and_resolve(map_service, "青岛北站", region="青岛")

    assert origin.city_code
    assert accommodation.city_code
    assert place.city_code == accommodation.city_code
    assert outbound_departure.city_code == origin.city_code
    assert outbound_arrival.city_code == accommodation.city_code

    trip_id = uuid4()
    state = TripState(
        trip_id=trip_id,
        revision=1,
        origin=_resolved_intent(origin),
        destination=_resolved_intent(accommodation),
        return_destination=_resolved_intent(origin),
        departure_date="2026-10-01",
        return_date="2026-10-01",
        accommodation=_resolved_intent(accommodation),
        places=[_resolved_intent(place)],
        intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
        local_travel_mode=TravelMode.PUBLIC_TRANSPORT,
    )
    request = PublicTransportPlanningRequest(
        trip_id=trip_id,
        outbound_intercity={
            "travel_mode": "high_speed_rail",
            "departure_poi_id": outbound_departure.poi_id,
            "arrival_poi_id": outbound_arrival.poi_id,
            "fact": {"service_identifier": "user-confirmed-outbound", "duration_seconds": 1},
        },
        return_intercity={
            "travel_mode": "high_speed_rail",
            "departure_poi_id": outbound_arrival.poi_id,
            "arrival_poi_id": outbound_departure.poi_id,
            "fact": {"service_identifier": "user-confirmed-return", "duration_seconds": 1},
        },
        daily_places=[{"day_number": 1, "place_poi_ids": [place.poi_id]}],
    )

    plan = PublicTransportTripPlanningService(map_service).plan(state, request)

    assert [leg.kind for leg in plan.legs] == [
        TripRouteLegKind.TO_OUTBOUND_DEPARTURE_NODE,
        TripRouteLegKind.OUTBOUND_INTERCITY,
        TripRouteLegKind.FROM_OUTBOUND_ARRIVAL_NODE,
        TripRouteLegKind.DAY_START,
        TripRouteLegKind.DAY_RETURN,
        TripRouteLegKind.TO_RETURN_DEPARTURE_NODE,
        TripRouteLegKind.RETURN_INTERCITY,
        TripRouteLegKind.FROM_RETURN_ARRIVAL_NODE,
    ]
    local_legs = [
        leg
        for leg in plan.legs
        if leg.fact_source is TripRouteFactSource.AMAP_LOCAL_PUBLIC_TRANSPORT
    ]
    assert len(local_legs) == 6
    assert all(leg.local_route is not None for leg in local_legs)
    assert all(leg.local_route.travel_mode is TravelMode.PUBLIC_TRANSPORT for leg in local_legs)
    assert all(leg.local_route.distance_meters >= 0 for leg in local_legs)
    assert all(leg.local_route.duration_seconds is not None for leg in local_legs)
    assert all(leg.local_route.segments for leg in local_legs)
    assert [
        leg.fact_source
        for leg in plan.legs
        if leg.kind
        in {TripRouteLegKind.OUTBOUND_INTERCITY, TripRouteLegKind.RETURN_INTERCITY}
    ] == [
        TripRouteFactSource.USER_CONFIRMED_INTERCITY,
        TripRouteFactSource.USER_CONFIRMED_INTERCITY,
    ]


def _search_and_resolve(
    map_service: "RetryingAmapMapService", keyword: str, *, region: str
) -> ResolvedLocation:
    candidates = map_service.search_pois(keyword, region=region)
    return map_service.resolve_location(candidates[0].poi_id)


def _resolved_intent(location: ResolvedLocation) -> dict[str, object]:
    return {
        "query": location.name,
        "resolution_status": "resolved",
        "resolved_location": location,
    }


class RetryingAmapMapService:
    """Retry transient upstream transport failures only within this opt-in Smoke Test."""

    def __init__(self, delegate: AmapApiService) -> None:
        self._delegate = delegate

    def search_pois(self, keyword: str, *, region: str) -> list[object]:
        return self._retry(lambda: self._delegate.search_pois(keyword, region=region))

    def resolve_location(self, poi_id: str) -> ResolvedLocation:
        return self._retry(lambda: self._delegate.resolve_location(poi_id))

    def get_local_public_transport_route(
        self, origin: ResolvedLocation, destination: ResolvedLocation
    ) -> Route:
        return self._retry(
            lambda: self._delegate.get_local_public_transport_route(origin, destination)
        )

    @staticmethod
    def _retry(operation):
        last_error: MapUpstreamError | None = None
        for _ in range(3):
            try:
                return operation()
            except MapUpstreamError as error:
                last_error = error
        assert last_error is not None
        raise last_error
