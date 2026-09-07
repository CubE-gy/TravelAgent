"""Opt-in real provider check for the user's two-turn Nanjing example."""

import pytest

from app.core.config import Settings
from app.schemas.trip_state import TripState
from app.services.amap_api_service import AmapApiService
from app.services.llm_provider_factory import create_llm_provider
from app.services.trip_state_extraction_service import TripStateExtractionService
from app.services.trip_state_location_resolution_service import TripStateLocationResolutionService
from app.services.trip_state_merger import merge_trip_state
from app.services.location_resolution_service import resolve_location_intent
from app.schemas.trip_state import LocationIntent


@pytest.mark.amap_smoke
def test_real_xuanwu_lake_selects_visitor_scenic_area():
    settings = Settings()
    if not settings.amap_web_api_key:
        pytest.skip("requires configured Amap credentials")
    result = resolve_location_intent(
        LocationIntent(query="玄武湖"), AmapApiService(settings.amap_web_api_key),
        region="025", city_name="南京市", field="places", auto_select=True,
    )
    assert result.resolved_location is not None
    assert result.resolved_location.name == "玄武湖景区"
    assert result.resolved_location.city_code == "025"
    assert result.resolved_location.category_code.startswith("11")


@pytest.mark.llm_smoke
@pytest.mark.amap_smoke
def test_real_nanjing_city_then_zhongshan_mausoleum():
    settings = Settings()
    if settings.llm_provider != "real" or not settings.llm_api_key or not settings.amap_web_api_key:
        pytest.skip("requires configured real LLM and Amap credentials")
    extractor = TripStateExtractionService(create_llm_provider(settings))
    maps = AmapApiService(settings.amap_web_api_key)
    resolver = TripStateLocationResolutionService(maps, city_service=maps, auto_select=True)
    state = TripState(trip_id="00000000-0000-0000-0000-000000000004")
    first = extractor.extract(state, "我想去南京")
    assert first.patch.destination is not None and first.patch.destination.query in {"南京", "南京市"}
    assert not first.patch.places
    result = resolver.resolve(merge_trip_state(state, first.patch))
    assert not result.failures
    state = result.state
    assert state.destination.resolved_city is not None
    assert state.destination.resolved_city.city_code == "025"
    assert state.destination.resolved_location is None

    second = extractor.extract(state, "我还想去中山陵")
    result = resolver.resolve(merge_trip_state(state, second.patch))
    assert not result.failures
    assert result.state.destination == state.destination
    assert len(result.state.places) == 1
    landmark = result.state.places[0].resolved_location
    assert landmark is not None
    assert "中山陵" in landmark.name
    assert landmark.city_code == "025"
    assert "停车场" not in landmark.name and "门" not in landmark.name
