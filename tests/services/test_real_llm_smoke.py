"""Opt-in evidence that a configured real LLM can produce Stage 2 state patches."""

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.models.enums import IntercityTravelMode, TravelMode
from app.schemas.trip_state import TripState
from app.services.llm_provider_factory import create_llm_provider
from app.services.trip_state_extraction_service import TripStateExtractionService
from app.services.trip_state_merger import merge_trip_state


def _is_real_llm_smoke_configured(settings: Settings) -> bool:
    """Return whether the real-provider smoke tests have non-blank credentials."""
    return (
        settings.llm_provider == "real"
        and settings.llm_api_key is not None
        and bool(settings.llm_api_key.get_secret_value().strip())
        and settings.llm_model is not None
        and bool(settings.llm_model.strip())
    )


@pytest.mark.parametrize(
    ("llm_provider", "llm_api_key", "llm_model", "expected"),
    [
        ("mock", SecretStr("key"), "model", False),
        ("real", None, "model", False),
        ("real", SecretStr("   "), "model", False),
        ("real", SecretStr("key"), None, False),
        ("real", SecretStr("key"), "   ", False),
        ("real", SecretStr("key"), "model", True),
    ],
)
def test_real_llm_smoke_configuration_requires_non_blank_values(
    llm_provider: str,
    llm_api_key: SecretStr | None,
    llm_model: str | None,
    expected: bool,
) -> None:
    settings = Settings.model_construct(
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
    )

    assert _is_real_llm_smoke_configured(settings) is expected


@pytest.mark.llm_smoke
@pytest.mark.parametrize(
    "message",
    [
        "我从南京新街口出发，2026年10月1日去北京，10月3日回南京新街口，"
        "城际坐高铁，当地坐公共交通，住王府井附近，想去故宫。",
        "2026 年国庆从南京新街口出发到北京玩，十月一号动身、三号返回原地；高铁往返，"
        "在王府井一带找住处，市内靠地铁公交，故宫一定要安排。",
    ],
)
def test_real_provider_extracts_required_trip_state_fields(message: str) -> None:
    settings = Settings()
    if not _is_real_llm_smoke_configured(settings):
        pytest.skip("configure LLM_PROVIDER=real, LLM_API_KEY, and LLM_MODEL to run this smoke test")

    understanding = TripStateExtractionService(create_llm_provider(settings)).extract(
        TripState(trip_id="00000000-0000-0000-0000-000000000001"),
        message,
    )

    patch = understanding.patch
    assert patch.origin is not None and patch.origin.query == "南京新街口"
    assert patch.destination is not None and patch.destination.query == "北京"
    assert patch.return_destination is not None and patch.return_destination.query == "南京新街口"
    assert str(patch.departure_date) == "2026-10-01"
    assert str(patch.return_date) == "2026-10-03"
    assert patch.intercity_travel_mode is IntercityTravelMode.HIGH_SPEED_RAIL
    assert patch.local_travel_mode is TravelMode.PUBLIC_TRANSPORT
    assert patch.accommodation is not None and "王府井" in patch.accommodation.query
    assert [place.query for place in patch.places or []] == ["故宫"]


@pytest.mark.llm_smoke
def test_real_provider_corrects_only_the_explicit_trip_state_fields() -> None:
    settings = Settings()
    if not _is_real_llm_smoke_configured(settings):
        pytest.skip("configure LLM_PROVIDER=real, LLM_API_KEY, and LLM_MODEL to run this smoke test")

    current_state = TripState(
        trip_id="00000000-0000-0000-0000-000000000002",
        origin={"query": "南京新街口"},
        destination={"query": "北京"},
        return_destination={"query": "南京新街口"},
        departure_date="2026-10-01",
        return_date="2026-10-03",
        accommodation={"query": "王府井附近"},
        places=[{"query": "故宫"}, {"query": "天坛"}],
        intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
        local_travel_mode=TravelMode.PUBLIC_TRANSPORT,
    )

    understanding = TripStateExtractionService(create_llm_provider(settings)).extract(
        current_state,
        "改坐飞机，酒店换到国贸附近，景点只保留故宫。",
    )

    patch = understanding.patch
    assert patch.model_fields_set == {
        "accommodation",
        "intercity_travel_mode",
        "places",
    }
    assert patch.intercity_travel_mode is IntercityTravelMode.FLIGHT
    assert patch.accommodation is not None and "国贸" in patch.accommodation.query
    assert [place.query for place in patch.places or []] == ["故宫"]

    merged_state = merge_trip_state(current_state, patch)
    assert merged_state.intercity_travel_mode is IntercityTravelMode.FLIGHT
    assert merged_state.accommodation is not None and "国贸" in merged_state.accommodation.query
    assert [place.query for place in merged_state.places] == ["故宫"]
    assert merged_state.origin == current_state.origin
    assert merged_state.destination == current_state.destination
    assert merged_state.return_destination == current_state.return_destination
    assert merged_state.departure_date == current_state.departure_date
    assert merged_state.return_date == current_state.return_date
    assert merged_state.local_travel_mode is current_state.local_travel_mode
