from uuid import uuid4

import pytest

from app.schemas.map import GeoPoint, PoiCandidate, ResolvedCity, ResolvedLocation
from app.schemas.trip_state import TripState
from app.services.trip_recommendation_service import TripRecommendationService


def location(poi_id: str, name: str, city_code: str = "025") -> ResolvedLocation:
    return ResolvedLocation(
        poi_id=poi_id, name=name, city_code=city_code,
        coordinate=GeoPoint(latitude=32.05, longitude=118.78),
    )


class FakeMapService:
    def __init__(self) -> None:
        self.nearby_calls: list[object] = []
        self.locations = {
            "hotel-1": location("hotel-1", "金陵饭店"),
            "hotel-2": location("hotel-2", "新街口酒店"),
            "wrong-city": location("wrong-city", "外地酒店", "010"),
        }

    def search_nearby_pois(self, center, **kwargs):
        self.nearby_calls.append((center, kwargs))
        return [PoiCandidate(**item.model_dump()) for item in self.locations.values()]

    def resolve_location(self, poi_id):
        return self.locations[poi_id]


def state() -> TripState:
    return TripState(trip_id=uuid4(), revision=3, destination={
        "query": "南京", "resolution_status": "resolved",
        "resolved_city": ResolvedCity(name="南京市", adcode="320100", city_code="025", center=GeoPoint(latitude=32.06, longitude=118.8)),
    })


def test_recommend_uses_destination_city_map_facts_and_excludes_other_cities() -> None:
    map_service = FakeMapService()
    results = TripRecommendationService(map_service).recommend(state(), "accommodation")

    assert [item.location.poi_id for item in results] == ["hotel-1", "hotel-2"]
    assert map_service.nearby_calls[0][1]["types"] == "100000"


def test_recommend_passes_a_refinement_keyword_to_the_map_search() -> None:
    map_service = FakeMapService()

    TripRecommendationService(map_service).recommend(state(), "accommodation", keyword="高档酒店")

    assert map_service.nearby_calls[0][1]["keyword"] == "高档酒店"


def test_select_recommendation_replaces_hotel_and_persists_only_clicked_poi(monkeypatch: pytest.MonkeyPatch) -> None:
    current = state()
    map_service = FakeMapService()
    saved = []
    monkeypatch.setattr("app.services.trip_recommendation_service.save_trip_state", lambda session, value, **kwargs: saved.append((value, kwargs)) or value.model_copy(update={"revision": 4}))
    monkeypatch.setattr("app.services.trip_recommendation_service.sync_trip_dates_from_state", lambda *args, **kwargs: None)

    result = TripRecommendationService(map_service).select(
        object(), current.trip_id, current, kind="accommodation", poi_id="hotel-1", expected_revision=3
    )

    assert result.state.accommodation is not None
    assert result.state.accommodation.resolved_location is not None
    assert result.state.accommodation.resolved_location.poi_id == "hotel-1"
    assert saved[0][1]["expected_revision"] == 3


def test_select_recommendation_rejects_a_poi_outside_destination_city() -> None:
    current = state()
    with pytest.raises(ValueError, match="destination city"):
        TripRecommendationService(FakeMapService()).select(
            object(), current.trip_id, current, kind="accommodation", poi_id="wrong-city", expected_revision=3
        )
