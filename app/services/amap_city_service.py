"""Exact city recognition using Amap administrative facts."""

from app.schemas.map import GeoPoint, ResolvedCity
from app.services.amap_poi_service import JsonMapClient
from app.services.map_errors import MapUpstreamError


class AmapCityService:
    def __init__(self, client: JsonMapClient) -> None:
        self._client = client

    def resolve_city(self, query: str) -> ResolvedCity | None:
        """Return an exact city (including municipalities), not a fuzzy district hit."""
        keyword = query.strip()
        if not keyword:
            raise ValueError("city query must not be blank")
        payload = self._client.get_json(
            "v3/config/district",
            params={"keywords": keyword, "subdistrict": 0, "extensions": "base"},
        )
        districts = payload.get("districts")
        if payload.get("status") != "1" or not isinstance(districts, list):
            raise MapUpstreamError()
        matches = []
        for district in districts:
            if not isinstance(district, dict) or not isinstance(district.get("name"), str):
                raise MapUpstreamError()
            name = district["name"]
            level = district.get("level")
            is_city = level == "city" or (
                level == "province" and name in {"北京市", "上海市", "天津市", "重庆市"}
            )
            if not is_city or name.removesuffix("市") != keyword.removesuffix("市"):
                continue
            try:
                longitude, latitude = district["center"].split(",")
                matches.append(ResolvedCity(
                    name=name, adcode=district["adcode"], city_code=district["citycode"],
                    center=GeoPoint(longitude=longitude, latitude=latitude),
                ))
            except (KeyError, AttributeError, TypeError, ValueError) as error:
                raise MapUpstreamError() from error
        return matches[0] if len(matches) == 1 else None
