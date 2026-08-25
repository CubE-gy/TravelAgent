import pytest

from app.models.enums import RouteSegmentMode, TravelMode
from app.schemas.map import GeoPoint, ResolvedLocation
from app.services.amap_route_service import AmapRouteService
from app.services.map_errors import MapNoResultsError, MapUpstreamError


class FakeMapClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, path: str, params: dict[str, str]) -> dict:
        self.calls.append((path, params))
        return self.payload


def resolved_location(poi_id: str, latitude: float, longitude: float) -> ResolvedLocation:
    return ResolvedLocation(
        poi_id=poi_id,
        name=poi_id,
        city_code="010",
        coordinate=GeoPoint(latitude=latitude, longitude=longitude),
    )


def test_driving_converts_a_v5_route_and_requests_required_fields() -> None:
    client = FakeMapClient(
        {
            "status": "1",
            "route": {
                "paths": [
                    {
                        "distance": "12500",
                        "cost": {"duration": "1500"},
                        "steps": [
                            {
                                "step_distance": "5000",
                                "cost": {"duration": "600"},
                                "polyline": "116.3975,39.9042;116.4000,39.9050",
                            },
                            {
                                "step_distance": "7500",
                                "cost": {"duration": "900"},
                                "polyline": "116.4000,39.9050;116.3972,39.9163",
                            },
                        ],
                    }
                ]
            },
        }
    )
    origin = resolved_location("B000A1", 39.9042, 116.3975)
    destination = resolved_location("B000A2", 39.9163, 116.3972)

    route = AmapRouteService(client).driving(origin, destination)

    assert route.travel_mode is TravelMode.DRIVING
    assert route.distance_meters == 12500
    assert route.duration_seconds == 1500
    assert [segment.distance_meters for segment in route.segments] == [5000, 7500]
    assert all(segment.mode is RouteSegmentMode.DRIVING for segment in route.segments)
    assert route.segments[0].polyline is not None
    assert route.segments[0].polyline.points[0] == GeoPoint(
        latitude=39.9042, longitude=116.3975
    )
    assert client.calls == [
        (
            "v5/direction/driving",
            {
                "origin": "116.397500,39.904200",
                "destination": "116.397200,39.916300",
                "origin_id": "B000A1",
                "destination_id": "B000A2",
                "show_fields": "cost,polyline",
            },
        )
    ]


def test_driving_converts_empty_paths_to_no_results() -> None:
    client = FakeMapClient({"status": "1", "route": {"paths": []}})

    with pytest.raises(MapNoResultsError):
        AmapRouteService(client).driving(
            resolved_location("B000A1", 39.9042, 116.3975),
            resolved_location("B000A2", 39.9163, 116.3972),
        )


def test_local_public_transport_converts_walking_bus_subway_and_railway_segments() -> None:
    client = FakeMapClient(
        {
            "status": "1",
            "route": {
                "transits": [
                    {
                        "distance": "8200",
                        "cost": {"duration": "1800"},
                        "segments": [
                            {
                                "walking": {
                                    "distance": "300",
                                    "duration": "240",
                                    "steps": [
                                        {
                                            "polyline": {
                                                "polyline": "116.3975,39.9042;116.3980,39.9045"
                                            }
                                        }
                                    ],
                                },
                                "bus": {
                                    "buslines": [
                                        {
                                            "type": "公交线路",
                                            "distance": "1200",
                                            "duration": "300",
                                            "polyline": "116.3980,39.9045;116.4050,39.9070",
                                        },
                                        {
                                            "type": "地铁线路",
                                            "distance": "6200",
                                            "duration": "1000",
                                            "polyline": "116.4050,39.9070;116.3972,39.9163",
                                        },
                                    ]
                                },
                                "railway": {"distance": "500", "time": "260"},
                            }
                        ],
                    }
                ]
            },
        }
    )
    origin = resolved_location("B000A1", 39.9042, 116.3975)
    destination = resolved_location("B000A2", 39.9163, 116.3972)

    route = AmapRouteService(client).local_public_transport(origin, destination)

    assert route.travel_mode is TravelMode.PUBLIC_TRANSPORT
    assert route.distance_meters == 8200
    assert route.duration_seconds == 1800
    assert [segment.mode for segment in route.segments] == [
        RouteSegmentMode.WALKING,
        RouteSegmentMode.BUS,
        RouteSegmentMode.SUBWAY,
        RouteSegmentMode.RAILWAY,
    ]
    assert route.segments[0].polyline is not None
    assert route.segments[-1].polyline is None
    assert client.calls == [
        (
            "v5/direction/transit/integrated",
            {
                "origin": "116.397500,39.904200",
                "destination": "116.397200,39.916300",
                "originpoi": "B000A1",
                "destinationpoi": "B000A2",
                "city1": "010",
                "city2": "010",
                "AlternativeRoute": "1",
                "show_fields": "cost,polyline",
            },
        )
    ]


def test_local_public_transport_rejects_missing_or_different_city_codes() -> None:
    client = FakeMapClient({})
    origin = resolved_location("B000A1", 39.9042, 116.3975)
    missing_city_code = origin.model_copy(update={"city_code": None})
    other_city = origin.model_copy(update={"city_code": "021"})

    with pytest.raises(ValueError, match="destination city_code is required"):
        AmapRouteService(client).local_public_transport(origin, missing_city_code)
    with pytest.raises(ValueError, match="same city"):
        AmapRouteService(client).local_public_transport(origin, other_city)

    assert client.calls == []


def test_local_public_transport_converts_empty_transits_to_no_results() -> None:
    client = FakeMapClient({"status": "1", "route": {"transits": []}})

    with pytest.raises(MapNoResultsError):
        AmapRouteService(client).local_public_transport(
            resolved_location("B000A1", 39.9042, 116.3975),
            resolved_location("B000A2", 39.9163, 116.3972),
        )


def test_local_public_transport_allows_missing_segment_durations() -> None:
    client = FakeMapClient(
        {
            "status": "1",
            "route": {
                "transits": [
                    {
                        "distance": "100",
                        "cost": {"duration": "120"},
                        "segments": [
                            {
                                "walking": {
                                    "distance": "100",
                                    "steps": [
                                        {
                                            "polyline": "116.3975,39.9042;116.3980,39.9045"
                                        }
                                    ],
                                }
                            }
                        ],
                    }
                ]
            },
        }
    )

    route = AmapRouteService(client).local_public_transport(
        resolved_location("B000A1", 39.9042, 116.3975),
        resolved_location("B000A2", 39.9045, 116.3980),
    )

    assert route.duration_seconds == 120
    assert route.segments[0].duration_seconds is None


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "0"},
        {"status": "1", "route": {"paths": [{"distance": "1", "steps": []}]}},
        {
            "status": "1",
            "route": {
                "paths": [
                    {
                        "distance": "1",
                        "cost": {"duration": "1"},
                        "steps": [
                            {
                                "step_distance": "1",
                                "cost": {"duration": "1"},
                                "polyline": "invalid",
                            }
                        ],
                    }
                ]
            },
        },
    ],
)
def test_driving_converts_invalid_v5_payloads_to_map_upstream_errors(payload: dict) -> None:
    with pytest.raises(MapUpstreamError):
        AmapRouteService(FakeMapClient(payload)).driving(
            resolved_location("B000A1", 39.9042, 116.3975),
            resolved_location("B000A2", 39.9163, 116.3972),
        )
