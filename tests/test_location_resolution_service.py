import pytest

from app.schemas.map import PoiCandidate, ResolvedLocation
from app.schemas.trip_state import LocationIntent, LocationResolutionStatus
from app.services.location_resolution_service import (
    confirm_location_candidate,
    resolve_location_intent,
)
from app.services.map_errors import MapNoResultsError, MapUpstreamError


class FakeLocationMapService:
    def __init__(
        self,
        candidates: list[PoiCandidate] | None = None,
        resolved_location: ResolvedLocation | None = None,
        search_error: Exception | None = None,
    ) -> None:
        self.candidates = candidates or []
        self.resolved_location = resolved_location
        self.search_error = search_error
        self.search_calls: list[tuple[str, str | None]] = []
        self.resolve_calls: list[str] = []

    def search_pois(self, keyword: str, *, region: str | None = None) -> list[PoiCandidate]:
        self.search_calls.append((keyword, region))
        if self.search_error is not None:
            raise self.search_error
        return self.candidates

    def resolve_location(self, poi_id: str) -> ResolvedLocation:
        self.resolve_calls.append(poi_id)
        assert self.resolved_location is not None
        return self.resolved_location


def poi_candidate(poi_id: str, name: str) -> PoiCandidate:
    return PoiCandidate(
        poi_id=poi_id,
        name=name,
        coordinate={"latitude": 39.9, "longitude": 116.4},
    )


def test_unique_candidate_is_confirmed_with_amap_detail() -> None:
    service = FakeLocationMapService(
        candidates=[poi_candidate("B000A1", "故宫博物院")],
        resolved_location=ResolvedLocation(
            poi_id="B000A1",
            name="故宫博物院",
            address="北京市东城区景山前街4号",
            coordinate={"latitude": 39.9163, "longitude": 116.3972},
        ),
    )
    location = LocationIntent(query="故宫")

    resolved = resolve_location_intent(location, service, region="北京")

    assert resolved.resolution_status is LocationResolutionStatus.RESOLVED
    assert resolved.query == "故宫"
    assert resolved.resolved_location is not None
    assert resolved.resolved_location.name == "故宫博物院"
    assert service.search_calls == [("故宫", "北京")]
    assert service.resolve_calls == ["B000A1"]
    assert location.resolution_status is LocationResolutionStatus.UNRESOLVED


def test_multiple_candidates_are_kept_for_user_confirmation() -> None:
    service = FakeLocationMapService(
        candidates=[
            poi_candidate("B000A1", "北京万达广场"),
            poi_candidate("B000A2", "上海万达广场"),
        ]
    )

    ambiguous = resolve_location_intent(LocationIntent(query="万达广场"), service)

    assert ambiguous.resolution_status is LocationResolutionStatus.AMBIGUOUS
    assert [candidate.name for candidate in ambiguous.candidates] == [
        "北京万达广场",
        "上海万达广场",
    ]
    assert ambiguous.resolved_location is None
    assert service.resolve_calls == []


def test_user_selected_candidate_is_confirmed_with_amap_detail() -> None:
    location = LocationIntent(
        query="万达广场",
        resolution_status=LocationResolutionStatus.AMBIGUOUS,
        candidates=[
            poi_candidate("B000A1", "北京万达广场"),
            poi_candidate("B000A2", "上海万达广场"),
        ],
    )
    service = FakeLocationMapService(
        resolved_location=ResolvedLocation(
            poi_id="B000A2",
            name="上海万达广场",
            address="上海市杨浦区",
            coordinate={"latitude": 31.2, "longitude": 121.5},
        )
    )

    resolved = confirm_location_candidate(location, "  B000A2  ", service)

    assert resolved.resolution_status is LocationResolutionStatus.RESOLVED
    assert resolved.query == "万达广场"
    assert resolved.resolved_location is not None
    assert resolved.resolved_location.poi_id == "B000A2"
    assert service.search_calls == []
    assert service.resolve_calls == ["B000A2"]
    assert location.resolution_status is LocationResolutionStatus.AMBIGUOUS


@pytest.mark.parametrize("selected_poi_id", ["B000MISSING", "   "])
def test_unknown_or_blank_candidate_is_rejected_without_detail_lookup(
    selected_poi_id: str,
) -> None:
    location = LocationIntent(
        query="万达广场",
        resolution_status=LocationResolutionStatus.AMBIGUOUS,
        candidates=[
            poi_candidate("B000A1", "北京万达广场"),
            poi_candidate("B000A2", "上海万达广场"),
        ],
    )
    service = FakeLocationMapService()

    with pytest.raises(ValueError):
        confirm_location_candidate(location, selected_poi_id, service)

    assert service.search_calls == []
    assert service.resolve_calls == []


@pytest.mark.parametrize(
    "location",
    [
        LocationIntent(query="故宫"),
        LocationIntent(
            query="故宫",
            resolution_status=LocationResolutionStatus.RESOLVED,
            resolved_location=ResolvedLocation(
                poi_id="B000A1",
                name="故宫博物院",
                coordinate={"latitude": 39.9163, "longitude": 116.3972},
            ),
        ),
    ],
)
def test_only_ambiguous_location_allows_candidate_confirmation(location: LocationIntent) -> None:
    service = FakeLocationMapService()

    with pytest.raises(ValueError, match="only ambiguous"):
        confirm_location_candidate(location, "B000A1", service)

    assert service.search_calls == []
    assert service.resolve_calls == []


@pytest.mark.parametrize("error", [MapNoResultsError(), MapUpstreamError()])
def test_map_errors_propagate_without_mutating_location(error: Exception) -> None:
    location = LocationIntent(query="不存在的地点")
    service = FakeLocationMapService(search_error=error)

    with pytest.raises(type(error)):
        resolve_location_intent(location, service)

    assert location.model_dump() == {
        "query": "不存在的地点",
        "resolution_status": LocationResolutionStatus.UNRESOLVED,
        "candidates": [],
        "resolved_location": None,
    }
    assert service.resolve_calls == []


@pytest.mark.parametrize(
    "location",
    [
        LocationIntent(
            query="万达广场",
            resolution_status=LocationResolutionStatus.AMBIGUOUS,
            candidates=[poi_candidate("B000A1", "北京万达广场"), poi_candidate("B000A2", "上海万达广场")],
        ),
        LocationIntent(
            query="故宫",
            resolution_status=LocationResolutionStatus.RESOLVED,
            resolved_location=ResolvedLocation(
                poi_id="B000A1",
                name="故宫博物院",
                coordinate={"latitude": 39.9163, "longitude": 116.3972},
            ),
        ),
    ],
)
def test_non_unresolved_location_is_not_queried_again(location: LocationIntent) -> None:
    service = FakeLocationMapService()

    with pytest.raises(ValueError, match="only unresolved"):
        resolve_location_intent(location, service)

    assert service.search_calls == []
    assert service.resolve_calls == []
