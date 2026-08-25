from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import ValidationError

from app.schemas.map import GeoPoint, PoiCandidate, ResolvedLocation
from app.services.map_errors import MapNoResultsError, MapUpstreamError


class JsonMapClient(Protocol):
    """The JSON request capability required by POI services."""

    def get_json(
        self,
        path: str,
        params: Mapping[str, str | int | float] | None = None,
    ) -> dict[str, Any]: ...


class AmapPoiService:
    """Converts Amap text-search responses into project POI candidates."""

    GAS_STATION_TYPE = "010100"
    CHARGING_STATION_TYPE = "011100"

    def __init__(self, client: JsonMapClient) -> None:
        self._client = client

    def search(self, keyword: str, *, region: str | None = None) -> list[PoiCandidate]:
        """Find normalized POI candidates for a text keyword."""
        normalized_keyword = self._require_text(keyword, field_name="keyword")
        params: dict[str, str] = {"keywords": normalized_keyword}
        if region is not None:
            normalized_region = region.strip()
            if normalized_region:
                params["region"] = normalized_region
                params["city_limit"] = "true"

        payload = self._client.get_json("v5/place/text", params=params)
        pois = self._get_successful_pois(payload)
        if not pois:
            raise MapNoResultsError()

        try:
            return [self._to_candidate(poi) for poi in pois]
        except (TypeError, ValidationError, ValueError) as error:
            raise MapUpstreamError() from error

    def resolve(self, poi_id: str) -> ResolvedLocation:
        """Retrieve one normalized, confirmed location by its POI ID."""
        normalized_poi_id = self._require_text(poi_id, field_name="poi_id")
        payload = self._client.get_json("v5/place/detail", params={"id": normalized_poi_id})
        pois = self._get_successful_pois(payload)
        if not pois:
            raise MapNoResultsError()
        if len(pois) != 1:
            raise MapUpstreamError()

        try:
            candidate = self._to_candidate(pois[0])
            return ResolvedLocation(**candidate.model_dump())
        except (TypeError, ValidationError, ValueError) as error:
            raise MapUpstreamError() from error

    def search_nearby(
        self,
        center: GeoPoint,
        *,
        keyword: str | None = None,
        types: str | None = None,
        radius_meters: int = 5000,
    ) -> list[PoiCandidate]:
        """Find nearby normalized POIs, ordered by the provider's distance sort."""
        if (
            isinstance(radius_meters, bool)
            or not isinstance(radius_meters, int)
            or not 0 <= radius_meters <= 50000
        ):
            raise ValueError("radius_meters must be between 0 and 50000")

        params: dict[str, str | int] = {
            "location": self._format_location(center),
            "radius": radius_meters,
            "sortrule": "distance",
        }
        self._add_optional_text(params, "keywords", keyword)
        self._add_optional_text(params, "types", types)
        if "keywords" not in params and "types" not in params:
            raise ValueError("keyword or types must be provided")

        payload = self._client.get_json("v5/place/around", params=params)
        pois = self._get_successful_pois(payload)
        if not pois:
            raise MapNoResultsError()

        try:
            return [self._to_candidate(poi) for poi in pois]
        except (TypeError, ValidationError, ValueError) as error:
            raise MapUpstreamError() from error

    def search_gas_stations(
        self, center: GeoPoint, *, radius_meters: int = 5000
    ) -> list[PoiCandidate]:
        """Find nearby gas stations without making a refueling decision."""
        return self.search_nearby(
            center,
            types=self.GAS_STATION_TYPE,
            radius_meters=radius_meters,
        )

    def search_charging_stations(
        self, center: GeoPoint, *, radius_meters: int = 5000
    ) -> list[PoiCandidate]:
        """Find nearby charging stations without making a charging decision."""
        return self.search_nearby(
            center,
            types=self.CHARGING_STATION_TYPE,
            radius_meters=radius_meters,
        )

    @staticmethod
    def _get_successful_pois(payload: dict[str, Any]) -> list[object]:
        if payload.get("status") != "1":
            raise MapUpstreamError()

        pois = payload.get("pois")
        if not isinstance(pois, list):
            raise MapUpstreamError()
        return pois

    @staticmethod
    def _to_candidate(poi: object) -> PoiCandidate:
        if not isinstance(poi, dict):
            raise TypeError("POI must be an object")

        location = poi.get("location")
        if not isinstance(location, str):
            raise TypeError("POI location must be a string")
        longitude, latitude = AmapPoiService._parse_location(location)

        poi_id = poi.get("id")
        name = poi.get("name")
        address = poi.get("address")
        category_name = poi.get("type")
        category_code = poi.get("typecode")
        city_code = poi.get("citycode")
        if not isinstance(poi_id, str) or not isinstance(name, str):
            raise TypeError("POI id and name must be strings")
        if address is not None and not isinstance(address, str):
            raise TypeError("POI address must be a string or null")
        if category_name is not None and not isinstance(category_name, str):
            raise TypeError("POI type must be a string or null")
        if category_code is not None and not isinstance(category_code, str):
            raise TypeError("POI typecode must be a string or null")
        if city_code is not None and not isinstance(city_code, str):
            raise TypeError("POI citycode must be a string or null")

        return PoiCandidate(
            poi_id=poi_id,
            name=name,
            address=address,
            category_name=category_name,
            category_code=category_code,
            city_code=city_code,
            coordinate=GeoPoint(latitude=latitude, longitude=longitude),
        )

    @staticmethod
    def _parse_location(location: str) -> tuple[float, float]:
        longitude_text, latitude_text = location.split(",")
        return float(longitude_text), float(latitude_text)

    @staticmethod
    def _format_location(point: GeoPoint) -> str:
        return ",".join(
            AmapPoiService._format_coordinate(value)
            for value in (point.longitude, point.latitude)
        )

    @staticmethod
    def _format_coordinate(value: float) -> str:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    @staticmethod
    def _add_optional_text(
        params: dict[str, str | int], parameter_name: str, value: str | None
    ) -> None:
        if value is None:
            return
        normalized_value = value.strip()
        if normalized_value:
            params[parameter_name] = normalized_value

    @staticmethod
    def _require_text(value: str, *, field_name: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError(f"{field_name} must not be blank")
        return normalized_value
