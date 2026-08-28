from typing import Any

from app.models.enums import TravelMode
from app.schemas.map import GeoPoint, ResolvedLocation
from app.services.amap_api_service import AmapApiService


class FakeMapClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get_json(
        self,
        path: str,
        params: dict[str, str | int | float] | None = None,
    ) -> dict[str, Any]:
        del params
        self.calls.append(path)
        return self.responses[path]


def test_unified_service_returns_normalized_poi_and_route_facts() -> None:
    client = FakeMapClient(
        {
            "v5/place/text": {
                "status": "1",
                "pois": [
                    {
                        "id": "B000A1",
                        "name": "天安门",
                        "address": "东城区",
                        "location": "116.3975,39.9042",
                    }
                ],
            },
            "v5/place/detail": {
                "status": "1",
                "pois": [
                    {
                        "id": "B000A1",
                        "name": "天安门",
                        "address": "东城区",
                        "citycode": "010",
                        "location": "116.3975,39.9042",
                    }
                ],
            },
            "v5/direction/driving": {
                "status": "1",
                "route": {
                    "paths": [
                        {
                            "distance": "200",
                            "cost": {"duration": "60"},
                            "steps": [
                                {
                                    "step_distance": "200",
                                    "cost": {"duration": "60"},
                                    "polyline": "116.3975,39.9042;116.3980,39.9045",
                                }
                            ],
                        }
                    ]
                },
            },
        }
    )
    service = AmapApiService(client=client)

    candidates = service.search_pois("天安门", region="北京")
    location = service.resolve_location(candidates[0].poi_id)
    route = service.get_driving_route(location, location)

    assert candidates[0].poi_id == "B000A1"
    assert location.city_code == "010"
    assert route.travel_mode is TravelMode.DRIVING
    assert route.segments[0].polyline is not None
    assert client.calls == [
        "v5/place/text",
        "v5/place/detail",
        "v5/direction/driving",
    ]


def test_unified_service_delegates_nearby_and_local_transport_queries() -> None:
    client = FakeMapClient(
        {
            "v5/place/around": {
                "status": "1",
                "pois": [
                    {
                        "id": "B000GAS",
                        "name": "加油站",
                        "location": "116.3975,39.9042",
                    }
                ],
            },
            "v5/direction/transit/integrated": {
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
                                        "duration": "120",
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
            },
        }
    )
    service = AmapApiService(client=client)
    center = GeoPoint(latitude=39.9042, longitude=116.3975)
    location = ResolvedLocation(
        poi_id="B000A1",
        name="天安门",
        city_code="010",
        coordinate=center,
    )

    gas_stations = service.search_gas_stations(center)
    route = service.get_local_public_transport_route(location, location)

    assert gas_stations[0].poi_id == "B000GAS"
    assert route.travel_mode is TravelMode.PUBLIC_TRANSPORT
    assert client.calls == ["v5/place/around", "v5/direction/transit/integrated"]
