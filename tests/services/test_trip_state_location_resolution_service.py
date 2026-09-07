from uuid import uuid4

from app.schemas.map import PoiCandidate, ResolvedLocation
from app.schemas.trip_state import LocationIntent, LocationResolutionStatus, TripState
from app.services.map_errors import MapNoResultsError, MapTimeoutError
from app.services.trip_state_location_resolution_service import (
    LocationResolutionFailure,
    TripStateLocationResolutionService,
)


class FakeLocationMapService:
    def __init__(
        self,
        search_results: dict[str, list[PoiCandidate] | Exception],
        resolved_locations: dict[str, ResolvedLocation],
    ) -> None:
        self.search_results = search_results
        self.resolved_locations = resolved_locations
        self.search_calls: list[str] = []
        self.resolve_calls: list[str] = []

    def search_pois(self, keyword: str, *, region: str | None = None) -> list[PoiCandidate]:
        del region
        self.search_calls.append(keyword)
        result = self.search_results[keyword]
        if isinstance(result, Exception):
            raise result
        return result

    def resolve_location(self, poi_id: str) -> ResolvedLocation:
        self.resolve_calls.append(poi_id)
        return self.resolved_locations[poi_id]


def candidate(
    poi_id: str, name: str, *, category_code: str | None = None, city_code: str | None = None
) -> PoiCandidate:
    return PoiCandidate(
        poi_id=poi_id,
        name=name,
        category_code=category_code,
        city_code=city_code,
        coordinate={"latitude": 39.9, "longitude": 116.4},
    )


def resolved_location(poi_id: str, name: str) -> ResolvedLocation:
    return ResolvedLocation(
        poi_id=poi_id,
        name=name,
        coordinate={"latitude": 39.9, "longitude": 116.4},
    )


def test_resolve_confirms_unresolved_locations_and_preserves_existing_ambiguity() -> None:
    state = TripState(
        trip_id=uuid4(),
        destination={"query": "北京"},
        accommodation={
            "query": "万达广场",
            "resolution_status": "ambiguous",
            "candidates": [candidate("B000H1", "北京万达广场"), candidate("B000H2", "上海万达广场")],
        },
        places=[{"query": "故宫"}],
    )
    service = FakeLocationMapService(
        search_results={
            "北京": [candidate("B000D1", "北京市")],
            "故宫": [candidate("B000P1", "故宫博物院"), candidate("B000P2", "沈阳故宫")],
        },
        resolved_locations={"B000D1": resolved_location("B000D1", "北京市")},
    )

    result = TripStateLocationResolutionService(service).resolve(state)

    assert result.state.destination is not None
    assert result.state.destination.resolution_status is LocationResolutionStatus.RESOLVED
    assert result.state.accommodation == state.accommodation
    assert result.state.places[0].resolution_status is LocationResolutionStatus.AMBIGUOUS
    assert result.failures == []
    assert service.search_calls == ["北京", "故宫"]
    assert service.resolve_calls == ["B000D1"]
    assert state.destination is not None
    assert state.destination.resolution_status is LocationResolutionStatus.UNRESOLVED


def test_resolve_records_map_failures_and_continues_other_locations() -> None:
    state = TripState(
        trip_id=uuid4(),
        destination={"query": "不存在的城市"},
        accommodation={"query": "暂时不可用的酒店"},
        places=[{"query": "故宫"}],
    )
    service = FakeLocationMapService(
        search_results={
            "不存在的城市": MapNoResultsError(),
            "暂时不可用的酒店": MapTimeoutError(),
            "故宫": [candidate("B000P1", "故宫博物院")],
        },
        resolved_locations={"B000P1": resolved_location("B000P1", "故宫博物院")},
    )

    result = TripStateLocationResolutionService(service).resolve(state)

    assert result.state.destination == state.destination
    assert result.state.accommodation == state.accommodation
    assert result.state.places[0].resolution_status is LocationResolutionStatus.RESOLVED
    assert result.failures == [
        LocationResolutionFailure(
            field="destination",
            query="不存在的城市",
            error_code="map_no_results",
        ),
        LocationResolutionFailure(
            field="accommodation",
            query="暂时不可用的酒店",
            error_code="map_timeout",
        ),
    ]
    assert service.search_calls == ["不存在的城市", "暂时不可用的酒店", "故宫"]
    assert service.resolve_calls == ["B000P1"]


def test_resolve_offers_multiple_city_rail_stations_for_user_confirmation() -> None:
    state = TripState(
        trip_id=uuid4(),
        origin={
            "query": "北京", "resolution_status": "resolved",
            "resolved_city": {"name": "北京市", "adcode": "110000", "city_code": "010", "center": {"latitude": 39.9, "longitude": 116.4}},
        },
        destination={
            "query": "南京", "resolution_status": "resolved",
            "resolved_city": {"name": "南京市", "adcode": "320100", "city_code": "025", "center": {"latitude": 32.1, "longitude": 118.8}},
        },
        intercity_travel_mode="high_speed_rail",
    )
    service = FakeLocationMapService(
        search_results={
            "北京高铁站": [candidate("BJ-S", "北京南站", category_code="150100", city_code="010"), candidate("BJ-F", "北京丰台站", category_code="150100", city_code="010")],
            "南京高铁站": [candidate("NJ-S", "南京南站", category_code="150100", city_code="025")],
        },
        resolved_locations={"NJ-S": resolved_location("NJ-S", "南京南站")},
    )

    result = TripStateLocationResolutionService(service).resolve(state)

    assert result.state.outbound_departure_station is not None
    assert result.state.outbound_departure_station.resolution_status is LocationResolutionStatus.AMBIGUOUS
    assert [candidate.name for candidate in result.state.outbound_departure_station.candidates] == ["北京南站", "北京丰台站"]
    assert result.state.outbound_arrival_station is not None
    assert result.state.outbound_arrival_station.resolved_location is not None
    assert result.state.outbound_arrival_station.resolved_location.name == "南京南站"
    assert service.search_calls == ["北京高铁站", "南京高铁站"]
