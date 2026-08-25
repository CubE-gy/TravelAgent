import pytest
from pydantic import ValidationError

from app.models.enums import RouteSegmentMode, TravelMode
from app.schemas.map import GeoPoint, Polyline, Route, RouteSegment


def test_route_accepts_driving_route_facts() -> None:
    route = Route(
        travel_mode=TravelMode.DRIVING,
        distance_meters=12500,
        duration_seconds=1500,
        segments=[
            RouteSegment(
                mode=RouteSegmentMode.DRIVING,
                distance_meters=12500,
                duration_seconds=1500,
                polyline=Polyline(
                    points=[
                        GeoPoint(latitude=39.9042, longitude=116.3975),
                        GeoPoint(latitude=39.9163, longitude=116.3972),
                    ]
                ),
            )
        ],
    )

    assert route.segments[0].mode is RouteSegmentMode.DRIVING
    assert route.segments[0].polyline is not None


def test_route_accepts_public_transport_with_walking_bus_and_railway_segments() -> None:
    route = Route(
        travel_mode=TravelMode.PUBLIC_TRANSPORT,
        distance_meters=8200,
        segments=[
            RouteSegment(mode=RouteSegmentMode.WALKING, distance_meters=350),
            RouteSegment(mode=RouteSegmentMode.SUBWAY, distance_meters=4200),
            RouteSegment(mode=RouteSegmentMode.RAILWAY, distance_meters=3650),
        ],
    )

    assert [segment.mode for segment in route.segments] == [
        RouteSegmentMode.WALKING,
        RouteSegmentMode.SUBWAY,
        RouteSegmentMode.RAILWAY,
    ]
    assert route.duration_seconds is None


@pytest.mark.parametrize(
    "route_data",
    [
        {
            "travel_mode": "driving",
            "distance_meters": -1,
            "segments": [{"mode": "driving", "distance_meters": 1}],
        },
        {"travel_mode": "driving", "distance_meters": 1, "segments": []},
        {
            "travel_mode": "driving",
            "distance_meters": 1,
            "segments": [{"mode": "flying", "distance_meters": 1}],
        },
    ],
)
def test_route_rejects_invalid_route_facts(route_data: dict) -> None:
    with pytest.raises(ValidationError):
        Route(**route_data)


@pytest.mark.parametrize("duration_seconds", [-1, 1.5])
def test_route_segment_rejects_an_invalid_duration(duration_seconds: object) -> None:
    with pytest.raises(ValidationError):
        RouteSegment(
            mode=RouteSegmentMode.DRIVING,
            distance_meters=1,
            duration_seconds=duration_seconds,
        )
