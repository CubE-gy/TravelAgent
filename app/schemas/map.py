from pydantic import BaseModel, Field, field_validator

from app.models.enums import RouteSegmentMode, TravelMode


class GeoPoint(BaseModel):
    """A geographic coordinate expressed in WGS84-compatible latitude and longitude."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Polyline(BaseModel):
    """An ordered route geometry made of at least two geographic points."""

    points: list[GeoPoint] = Field(min_length=2)


class RouteSegment(BaseModel):
    """One contiguous part of a route returned by a map provider."""

    mode: RouteSegmentMode
    distance_meters: int = Field(ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)
    polyline: Polyline | None = None


class Route(BaseModel):
    """A complete route expressed through provider-independent map facts."""

    travel_mode: TravelMode
    distance_meters: int = Field(ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)
    segments: list[RouteSegment] = Field(min_length=1)


class _Poi(BaseModel):
    """Common normalized map facts for a point of interest."""

    poi_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    category_name: str | None = Field(default=None, max_length=200)
    category_code: str | None = Field(default=None, max_length=50)
    city_code: str | None = Field(default=None, max_length=50)
    coordinate: GeoPoint

    @field_validator("poi_id", "name")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("value must not be blank")
        return normalized_value

    @field_validator("address", "category_name", "category_code", "city_code")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class PoiCandidate(_Poi):
    """A normalized POI offered when a place search has one or more matches."""


class ResolvedCity(BaseModel):
    """An administrative city for map framing, never a routable POI."""

    name: str = Field(min_length=1, max_length=200)
    adcode: str = Field(pattern=r"^\d{6}$")
    city_code: str = Field(min_length=1, max_length=50)
    center: GeoPoint


class ResolvedLocation(_Poi):
    """A user-confirmed map location that can be used for route queries."""
