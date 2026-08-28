import pytest

from app.schemas.map import GeoPoint, Polyline
from app.services.amap_polyline import parse_amap_polyline
from app.services.map_errors import MapUpstreamError


def test_parse_amap_polyline_converts_longitude_latitude_points() -> None:
    polyline = parse_amap_polyline(
        "116.397500,39.904200;116.397800,39.904500;116.398100,39.904700"
    )

    assert polyline == Polyline(
        points=[
            GeoPoint(latitude=39.9042, longitude=116.3975),
            GeoPoint(latitude=39.9045, longitude=116.3978),
            GeoPoint(latitude=39.9047, longitude=116.3981),
        ]
    )


@pytest.mark.parametrize(
    "raw_polyline",
    [
        "",
        "116.397500,39.904200",
        "116.397500|39.904200;116.397800,39.904500",
        "not-a-number,39.904200;116.397800,39.904500",
        "181,39.904200;116.397800,39.904500",
    ],
)
def test_parse_amap_polyline_converts_invalid_input_to_map_upstream_error(
    raw_polyline: str,
) -> None:
    with pytest.raises(MapUpstreamError):
        parse_amap_polyline(raw_polyline)
