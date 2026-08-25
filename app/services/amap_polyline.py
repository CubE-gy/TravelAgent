from pydantic import ValidationError

from app.schemas.map import GeoPoint, Polyline
from app.services.map_errors import MapUpstreamError


def parse_amap_polyline(raw_polyline: str) -> Polyline:
    """Convert Amap's longitude,latitude point string into an internal polyline."""
    try:
        points = [_parse_point(raw_point) for raw_point in raw_polyline.strip().split(";")]
        return Polyline(points=points)
    except (AttributeError, TypeError, ValidationError, ValueError) as error:
        raise MapUpstreamError() from error


def _parse_point(raw_point: str) -> GeoPoint:
    longitude_text, latitude_text = raw_point.split(",")
    return GeoPoint(latitude=float(latitude_text), longitude=float(longitude_text))
