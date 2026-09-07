"""City context and automatic POI decisions for the map workspace."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.map import PoiCandidate, ResolvedCity, ResolvedLocation
from app.schemas.trip_state import LocationIntent, TripState
from app.services.amap_city_service import AmapCityService
from app.services.location_resolution_service import resolve_location_intent
from app.services.map_errors import MapNoResultsError, MapTimeoutError, MapUpstreamError
from app.services.trip_state_location_resolution_service import TripStateLocationResolutionService
from app.services.trip_route_skeleton_service import TripRouteSkeletonService


CITY = ResolvedCity(name="南京市", adcode="320100", city_code="025",
                    center={"latitude": 32.06, "longitude": 118.8})


class DistrictClient:
    def __init__(self, districts, status="1"):
        self.districts = districts
        self.status = status
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append((path, params))
        return {"status": self.status, "districts": self.districts}


def district(name="南京市", level="city", **changes):
    return {"name": name, "level": level, "adcode": "320100", "citycode": "025",
            "center": "118.8,32.06", **changes}


@pytest.mark.parametrize("query,name,level", [("南京", "南京市", "city"), ("南京市", "南京市", "city"), ("北京", "北京市", "province")])
def test_exact_city_uses_administrative_facts_without_a_poi(query, name, level):
    client = DistrictClient([district(name, level)])
    city = AmapCityService(client).resolve_city(query)
    assert city.name == name
    assert city.center.longitude == 118.8
    assert not hasattr(city, "poi_id")
    assert client.calls == [("v3/config/district", {"keywords": query, "subdistrict": 0, "extensions": "base"})]


@pytest.mark.parametrize("query,results", [("中山陵", []), ("南京站", [district()]),
    ("江苏", [district("江苏省", "province")]), ("朝阳", [district("朝阳区", "district")]),
    ("南京", [district(), district()])])
def test_non_city_fuzzy_or_non_unique_administrative_hits_are_not_city_facts(query, results):
    assert AmapCityService(DistrictClient(results)).resolve_city(query) is None


@pytest.mark.parametrize("results", [None, [None], [district(center="bad")], [district(citycode=[])], [district(adcode="bad")]])
def test_malformed_city_facts_are_reported_as_upstream_failure(results):
    with pytest.raises(MapUpstreamError):
        AmapCityService(DistrictClient(results)).resolve_city("南京")


def poi(poi_id, name, city_code="025", category_code="110200"):
    return PoiCandidate(poi_id=poi_id, name=name, city_code=city_code, category_code=category_code,
                        coordinate={"latitude": 32.06, "longitude": 118.85})


class MapFacts:
    def __init__(self, candidates=None):
        self.candidates = candidates or []
        self.search_calls = []
        self.detail_calls = []
        self.city_calls = []

    def resolve_city(self, query):
        self.city_calls.append(query)
        return CITY if query in {"南京", "南京市"} else None

    def search_pois(self, query, *, region=None):
        self.search_calls.append((query, region))
        return self.candidates

    def resolve_location(self, poi_id):
        self.detail_calls.append(poi_id)
        return ResolvedLocation(**next(item for item in self.candidates if item.poi_id == poi_id).model_dump())


def test_city_then_attraction_resolves_in_one_turn_and_round_trips_as_json():
    facts = MapFacts([poi("parking", "中山陵停车场", category_code="150900"),
                      poi("sun", "中山陵"), poi("gate", "中山陵南门")])
    state = TripState(trip_id=uuid4(), destination={"query": "南京"}, places=[{"query": "中山陵"}])
    result = TripStateLocationResolutionService(facts, city_service=facts, auto_select=True).resolve(state)
    assert result.failures == []
    assert result.state.destination.resolved_city == CITY
    assert result.state.destination.resolved_location is None
    assert result.state.places[0].resolved_location.poi_id == "sun"
    assert facts.search_calls == [("中山陵", "025")]
    assert facts.detail_calls == ["sun"]
    assert TripState.model_validate_json(result.state.model_dump_json()) == result.state
    assert state.destination.resolved_city is None


def test_next_turn_uses_persisted_city_and_preserves_already_resolved_pois():
    facts = MapFacts([poi("lake", "玄武湖")])
    sun = LocationIntent(query="中山陵", resolution_status="resolved",
        resolved_location=ResolvedLocation(**poi("sun", "中山陵").model_dump()))
    state = TripState(trip_id=uuid4(), destination=LocationIntent(query="南京", resolution_status="resolved", resolved_city=CITY),
                      places=[sun, LocationIntent(query="玄武湖")])
    result = TripStateLocationResolutionService(facts, city_service=facts, auto_select=True).resolve(state)
    assert result.state.places[0] == sun
    assert facts.city_calls == []
    assert facts.search_calls == [("玄武湖", "025")]


@pytest.mark.parametrize("candidates,expected", [
    ([poi("wrong", "中山陵", "010"), poi("sun", "中山陵")], "sun"),
    ([poi("sun", "中山陵景区"), poi("gate", "中山陵南门")], "sun"),
    ([poi("sun", "钟山风景名胜区-中山陵景区"), poi("parking", "中山陵停车场")], "sun"),
    ([poi("a", "中山陵"), poi("b", "中山陵")], None),
])
def test_automatic_selection_uses_city_name_and_main_poi_not_provider_order(candidates, expected):
    facts = MapFacts(candidates)
    result = resolve_location_intent(LocationIntent(query="中山陵"), facts,
        region="025", city_name="南京市", field="places", auto_select=True)
    assert (result.resolved_location.poi_id if result.resolved_location else None) == expected
    assert facts.detail_calls == ([expected] if expected else [])


def test_generic_chain_hotel_stays_pending_instead_of_choosing_arbitrary_branch():
    facts = MapFacts([poi("a", "如家酒店甲店", category_code="100100"), poi("b", "如家酒店乙店", category_code="100100")])
    result = resolve_location_intent(LocationIntent(query="如家酒店"), facts,
        region="025", city_name="南京市", field="accommodation", auto_select=True)
    assert result.resolution_status == "ambiguous"
    assert facts.detail_calls == []


def test_sightseeing_prefers_scenic_area_over_same_named_lake_center():
    facts = MapFacts([poi("lake-center", "玄武湖", category_code="190205"),
                      poi("lake-park", "玄武湖景区", category_code="110202"),
                      poi("lake-gate", "玄武湖景区玄武门游客中心", category_code="070201")])
    result = resolve_location_intent(LocationIntent(query="玄武湖"), facts,
        region="025", city_name="南京市", field="places", auto_select=True)
    assert result.resolved_location.poi_id == "lake-park"
    assert facts.detail_calls == ["lake-park"]


@pytest.mark.parametrize("candidates", [[], [poi("x", "其他景点")], [poi("parking", "中山陵停车场")], [poi("x", "中山陵", "010")]])
def test_empty_unrelated_ancillary_or_wrong_city_results_never_create_a_marker(candidates):
    with pytest.raises(MapNoResultsError):
        resolve_location_intent(LocationIntent(query="中山陵"), MapFacts(candidates),
            region="025", city_name="南京市", field="places", auto_select=True)


def test_detail_identity_must_match_selected_candidate():
    facts = MapFacts([poi("sun", "中山陵")])
    facts.resolve_location = lambda _: ResolvedLocation(**poi("wrong", "玄武湖").model_dump())
    with pytest.raises(MapUpstreamError):
        resolve_location_intent(LocationIntent(query="中山陵"), facts, auto_select=True)


def test_city_timeout_preserves_query_without_falling_back_to_random_poi():
    facts = MapFacts()
    def timeout(_):
        raise MapTimeoutError()
    facts.resolve_city = timeout
    result = TripStateLocationResolutionService(facts, city_service=facts, auto_select=True).resolve(
        TripState(trip_id=uuid4(), destination={"query": "南京"}))
    assert result.state.destination.resolution_status == "unresolved"
    assert result.failures[0].error_code == "map_timeout"
    assert facts.search_calls == []


def test_city_is_not_accepted_as_a_route_endpoint_or_mixed_with_poi_facts():
    city_intent = LocationIntent(query="南京", resolution_status="resolved", resolved_city=CITY)
    with pytest.raises(ValueError):
        TripRouteSkeletonService._require_resolved_location(city_intent, field_name="origin")
    with pytest.raises(ValidationError):
        LocationIntent(query="南京", resolution_status="resolved", resolved_city=CITY,
                       resolved_location=ResolvedLocation(**poi("x", "南京站").model_dump()))
