from pydantic import ValidationError

from app.schemas.map import GeoPoint, Polyline
from app.services.map_errors import MapUpstreamError


def parse_amap_polyline(raw_polyline: str) -> Polyline:
    """Convert Amap's longitude,latitude point string into an internal polyline."""
    try:
        return Polyline(points=parse_amap_polyline_points(raw_polyline))
    except (AttributeError, TypeError, ValidationError, ValueError) as error:
        raise MapUpstreamError() from error


def parse_amap_polyline_points(raw_polyline: str) -> list[GeoPoint]:
    """Parse and validate Amap polyline coordinates without requiring route geometry."""
    try:
        return [_parse_point(raw_point) for raw_point in raw_polyline.strip().split(";")]
    except (AttributeError, TypeError, ValidationError, ValueError) as error:
        raise MapUpstreamError() from error


def _parse_point(raw_point: str) -> GeoPoint:
    longitude_text, latitude_text = raw_point.split(",")
    return GeoPoint(latitude=float(latitude_text), longitude=float(longitude_text))
