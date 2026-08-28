from collections.abc import Mapping
from typing import Any

import pytest

from app.core.config import Settings
from app.models.enums import TravelMode
from app.schemas.map import ResolvedLocation
from app.services.amap_api_service import AmapApiService
from app.services.amap_client import AmapWebApiClient
from app.services.map_errors import MapUpstreamError


pytestmark = pytest.mark.amap_smoke


def test_amap_v5_poi_and_route_smoke() -> None:
    """Verify real V5 POI, driving, and city-local transit requests end to end."""
    settings = Settings()
    if settings.amap_web_api_key is None or not settings.amap_web_api_key.get_secret_value().strip():
        pytest.skip("AMAP_WEB_API_KEY is not configured")

    client = RecordingAmapClient(settings.amap_web_api_key)
    service = AmapApiService(client=client)
    origin = _search_and_resolve(service, "天安门")
    destination = _search_and_resolve(service, "故宫博物院")

    assert origin.poi_id
    assert origin.name
    assert origin.coordinate.latitude != 0
    assert origin.coordinate.longitude != 0
    assert origin.city_code
    assert destination.city_code == origin.city_code

    driving_route = service.get_driving_route(origin, destination)
    assert driving_route.travel_mode is TravelMode.DRIVING
    assert driving_route.distance_meters >= 0
    assert driving_route.duration_seconds is not None
    assert driving_route.segments

    try:
        public_transport_route = service.get_local_public_transport_route(origin, destination)
    except MapUpstreamError:
        raise AssertionError(
            "V5 transit response shape: "
            f"{_describe_shape(client.payloads[-1])}"
        ) from None
    assert public_transport_route.travel_mode is TravelMode.PUBLIC_TRANSPORT
    assert public_transport_route.distance_meters >= 0
    assert public_transport_route.duration_seconds is not None
    assert public_transport_route.segments


def _search_and_resolve(service: AmapApiService, keyword: str) -> ResolvedLocation:
    candidates = service.search_pois(keyword, region="北京")
    return service.resolve_location(candidates[0].poi_id)


class RecordingAmapClient(AmapWebApiClient):
    """Retain payloads in memory solely for a redacted smoke-test failure message."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.payloads: list[dict[str, Any]] = []

    def get_json(
        self,
        path: str,
        params: Mapping[str, str | int | float] | None = None,
    ) -> dict[str, Any]:
        payload = super().get_json(path, params)
        self.payloads.append(payload)
        return payload


def _describe_shape(value: object, *, depth: int = 0) -> object:
    """Describe only JSON container keys and value types; never include values."""
    if depth >= 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {str(key): _describe_shape(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        if not value:
            return "list(empty)"
        return [
            _describe_shape(value[0], depth=depth + 1),
            f"list(length={len(value)})",
        ]
    return type(value).__name__
