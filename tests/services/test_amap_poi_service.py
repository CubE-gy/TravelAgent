import pytest

from app.schemas.map import GeoPoint, PoiCandidate, ResolvedLocation
from app.services.amap_poi_service import AmapPoiService
from app.services.map_errors import MapNoResultsError, MapUpstreamError


class FakeMapClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get_json(self, path: str, params: dict[str, str | int] | None = None) -> dict:
        self.calls.append((path, params))
        return self.payload


def test_search_converts_amap_pois_to_candidates() -> None:
    client = FakeMapClient(
        {
            "status": "1",
            "pois": [
                {
                    "id": "B000A1",
                    "name": "天安门",
                    "address": "北京市东城区东长安街",
                    "type": "风景名胜",
                    "typecode": "110000",
                    "citycode": "010",
                    "location": "116.3975,39.9042",
                },
                {
                    "id": "B000A2",
                    "name": "故宫博物院",
                    "location": "116.3972,39.9163",
                },
            ],
        }
    )

    candidates = AmapPoiService(client).search("  天安门  ")

    assert candidates == [
        PoiCandidate(
            poi_id="B000A1",
            name="天安门",
            address="北京市东城区东长安街",
            category_name="风景名胜",
            category_code="110000",
            city_code="010",
            coordinate=GeoPoint(latitude=39.9042, longitude=116.3975),
        ),
        PoiCandidate(
            poi_id="B000A2",
            name="故宫博物院",
            coordinate=GeoPoint(latitude=39.9163, longitude=116.3972),
        ),
    ]
    assert client.calls == [("v5/place/text", {"keywords": "天安门"})]


def test_search_passes_a_non_blank_region_with_a_strict_city_limit() -> None:
    client = FakeMapClient(
        {
            "status": "1",
            "pois": [
                {
                    "id": "B000A1",
                    "name": "天安门",
                    "location": "116.3975,39.9042",
                }
            ],
        }
    )

    AmapPoiService(client).search("天安门", region="  110000  ")

    assert client.calls == [
        (
            "v5/place/text",
            {"keywords": "天安门", "region": "110000", "city_limit": "true"},
        )
    ]


def test_search_omits_a_blank_region() -> None:
    client = FakeMapClient(
        {
            "status": "1",
            "pois": [
                {"id": "B000A1", "name": "天安门", "location": "116.3975,39.9042"}
            ],
        }
    )

    AmapPoiService(client).search("天安门", region="  ")

    assert client.calls == [("v5/place/text", {"keywords": "天安门"})]


def test_search_rejects_a_blank_keyword_before_requesting() -> None:
    client = FakeMapClient({})

    with pytest.raises(ValueError, match="keyword must not be blank"):
        AmapPoiService(client).search("  ")

    assert client.calls == []


def test_search_converts_no_pois_to_no_results() -> None:
    client = FakeMapClient({"status": "1", "pois": []})

    with pytest.raises(MapNoResultsError):
        AmapPoiService(client).search("不存在的地点")


def test_resolve_converts_one_v5_poi_to_a_resolved_location() -> None:
    client = FakeMapClient(
        {
            "status": "1",
            "pois": [
                {
                    "id": "B000A1",
                    "name": "天安门",
                    "address": "北京市东城区东长安街",
                    "citycode": "010",
                    "location": "116.3975,39.9042",
                }
            ],
        }
    )

    location = AmapPoiService(client).resolve("  B000A1  ")

    assert location == ResolvedLocation(
        poi_id="B000A1",
        name="天安门",
        address="北京市东城区东长安街",
        city_code="010",
        coordinate=GeoPoint(latitude=39.9042, longitude=116.3975),
    )
    assert client.calls == [("v5/place/detail", {"id": "B000A1"})]


def test_search_nearby_passes_v5_distance_sorted_parameters() -> None:
    client = FakeMapClient(
        {
            "status": "1",
            "pois": [
                {"id": "B000A1", "name": "加油站", "location": "116.3975,39.9042"}
            ],
        }
    )

    candidates = AmapPoiService(client).search_nearby(
        GeoPoint(latitude=39.9042123, longitude=116.3975123),
        keyword="  加油站  ",
        types="  010100  ",
        radius_meters=10000,
    )

    assert candidates[0].name == "加油站"
    assert client.calls == [
        (
            "v5/place/around",
            {
                "location": "116.397512,39.904212",
                "radius": 10000,
                "sortrule": "distance",
                "keywords": "加油站",
                "types": "010100",
            },
        )
    ]


@pytest.mark.parametrize("radius_meters", [-1, 50001, True, 100.5])
def test_search_nearby_rejects_an_invalid_radius(radius_meters: object) -> None:
    client = FakeMapClient({})

    with pytest.raises(ValueError, match="radius_meters must be between 0 and 50000"):
        AmapPoiService(client).search_nearby(
            GeoPoint(latitude=39.9042, longitude=116.3975),
            keyword="加油站",
            radius_meters=radius_meters,
        )

    assert client.calls == []


def test_search_nearby_requires_a_keyword_or_type() -> None:
    client = FakeMapClient({})

    with pytest.raises(ValueError, match="keyword or types must be provided"):
        AmapPoiService(client).search_nearby(
            GeoPoint(latitude=39.9042, longitude=116.3975), keyword="  ", types="  "
        )

    assert client.calls == []


def test_search_nearby_converts_no_pois_to_no_results() -> None:
    client = FakeMapClient({"status": "1", "pois": []})

    with pytest.raises(MapNoResultsError):
        AmapPoiService(client).search_nearby(
            GeoPoint(latitude=39.9042, longitude=116.3975), types="010100"
        )


@pytest.mark.parametrize(
    ("method_name", "type_code"),
    [
        ("search_gas_stations", "010100"),
        ("search_charging_stations", "011100"),
    ],
)
def test_specialized_station_searches_use_their_amap_type_codes(
    method_name: str, type_code: str
) -> None:
    client = FakeMapClient(
        {
            "status": "1",
            "pois": [
                {
                    "id": "B000A1",
                    "name": "补能站",
                    "type": "汽车服务",
                    "typecode": type_code,
                    "location": "116.3975,39.9042",
                }
            ],
        }
    )
    service = AmapPoiService(client)

    candidates = getattr(service, method_name)(
        GeoPoint(latitude=39.9042, longitude=116.3975), radius_meters=10000
    )

    assert candidates[0].category_code == type_code
    assert client.calls == [
        (
            "v5/place/around",
            {
                "location": "116.3975,39.9042",
                "radius": 10000,
                "sortrule": "distance",
                "types": type_code,
            },
        )
    ]


def test_resolve_rejects_a_blank_poi_id_before_requesting() -> None:
    client = FakeMapClient({})

    with pytest.raises(ValueError, match="poi_id must not be blank"):
        AmapPoiService(client).resolve("  ")

    assert client.calls == []


@pytest.mark.parametrize(
    "payload, error_type",
    [
        ({"status": "1", "pois": []}, MapNoResultsError),
        (
            {
                "status": "1",
                "pois": [
                    {"id": "B000A1", "name": "天安门", "location": "116.3975,39.9042"},
                    {"id": "B000A2", "name": "故宫", "location": "116.3972,39.9163"},
                ],
            },
            MapUpstreamError,
        ),
    ],
)
def test_resolve_converts_invalid_result_counts(payload: dict, error_type: type[Exception]) -> None:
    with pytest.raises(error_type):
        AmapPoiService(FakeMapClient(payload)).resolve("B000A1")


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "0", "info": "INVALID_USER_KEY"},
        {"status": "1"},
        {
            "status": "1",
            "pois": [
                {"id": "B000A1", "name": "天安门", "location": "invalid-coordinate"}
            ],
        },
        {"status": "1", "pois": [{"id": "B000A1", "location": "116.3975,39.9042"}]},
    ],
)
def test_search_converts_invalid_amap_payloads(payload: dict) -> None:
    with pytest.raises(MapUpstreamError):
        AmapPoiService(FakeMapClient(payload)).search("天安门")
