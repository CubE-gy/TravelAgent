import pytest
from pydantic import ValidationError

from app.schemas.map import GeoPoint, PoiCandidate, ResolvedLocation


def test_geo_point_accepts_valid_coordinates() -> None:
    point = GeoPoint(latitude=39.9042, longitude=116.4074)

    assert point.latitude == 39.9042
    assert point.longitude == 116.4074


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(-90.1, 0), (90.1, 0), (0, -180.1), (0, 180.1)],
)
def test_geo_point_rejects_out_of_range_coordinates(
    latitude: float, longitude: float
) -> None:
    with pytest.raises(ValidationError):
        GeoPoint(latitude=latitude, longitude=longitude)


def test_poi_candidate_normalizes_map_facts() -> None:
    candidate = PoiCandidate(
        poi_id="  B000A1  ",
        name="  天安门  ",
        address="  北京市东城区东长安街  ",
        category_name="  风景名胜  ",
        category_code="  110000  ",
        city_code="  010  ",
        coordinate={"latitude": 39.9042, "longitude": 116.3975},
    )

    assert candidate.poi_id == "B000A1"
    assert candidate.name == "天安门"
    assert candidate.address == "北京市东城区东长安街"
    assert candidate.category_name == "风景名胜"
    assert candidate.category_code == "110000"
    assert candidate.city_code == "010"
    assert candidate.coordinate == GeoPoint(latitude=39.9042, longitude=116.3975)


def test_resolved_location_allows_missing_address() -> None:
    location = ResolvedLocation(
        poi_id="B000A2",
        name="故宫博物院",
        coordinate={"latitude": 39.9163, "longitude": 116.3972},
    )

    assert location.address is None


@pytest.mark.parametrize("field_name", ["poi_id", "name"])
def test_poi_models_reject_blank_required_text(field_name: str) -> None:
    fields = {
        "poi_id": "B000A1",
        "name": "天安门",
        "coordinate": {"latitude": 39.9042, "longitude": 116.3975},
    }
    fields[field_name] = "   "

    with pytest.raises(ValidationError):
        PoiCandidate(**fields)
