"""Unified project-facing access to Amap map facts."""

from pydantic import SecretStr

from app.schemas.map import GeoPoint, PoiCandidate, ResolvedLocation, Route
from app.services.amap_client import AmapWebApiClient
from app.services.amap_poi_service import AmapPoiService, JsonMapClient
from app.services.amap_route_service import AmapRouteService


class AmapApiService:
    """Expose normalized map facts without exposing Amap response structures."""

    def __init__(
        self,
        api_key: SecretStr | None = None,
        *,
        client: JsonMapClient | None = None,
    ) -> None:
        map_client = client or AmapWebApiClient(api_key)
        self._poi_service = AmapPoiService(map_client)
        self._route_service = AmapRouteService(map_client)

    def search_pois(
        self, keyword: str, *, region: str | None = None
    ) -> list[PoiCandidate]:
        """Return normalized POI candidates for a user-entered place."""
        return self._poi_service.search(keyword, region=region)

    def resolve_location(self, poi_id: str) -> ResolvedLocation:
        """Return one confirmed normalized location by POI ID."""
        return self._poi_service.resolve(poi_id)

    def search_nearby_pois(
        self,
        center: GeoPoint,
        *,
        keyword: str | None = None,
        types: str | None = None,
        radius_meters: int = 5000,
    ) -> list[PoiCandidate]:
        """Return nearby normalized POIs without making a business decision."""
        return self._poi_service.search_nearby(
            center,
            keyword=keyword,
            types=types,
            radius_meters=radius_meters,
        )

    def search_gas_stations(
        self, center: GeoPoint, *, radius_meters: int = 5000
    ) -> list[PoiCandidate]:
        """Return nearby gas-station facts."""
        return self._poi_service.search_gas_stations(center, radius_meters=radius_meters)

    def search_charging_stations(
        self, center: GeoPoint, *, radius_meters: int = 5000
    ) -> list[PoiCandidate]:
        """Return nearby charging-station facts."""
        return self._poi_service.search_charging_stations(
            center, radius_meters=radius_meters
        )

    def get_driving_route(
        self, origin: ResolvedLocation, destination: ResolvedLocation
    ) -> Route:
        """Return one normalized driving route between confirmed locations."""
        return self._route_service.driving(origin, destination)

    def get_local_public_transport_route(
        self, origin: ResolvedLocation, destination: ResolvedLocation
    ) -> Route:
        """Return one normalized city-local public transport route."""
        return self._route_service.local_public_transport(origin, destination)
