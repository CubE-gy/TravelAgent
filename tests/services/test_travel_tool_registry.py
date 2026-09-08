"""The travel tool registry is a small, allow-listed index of executors."""

import pytest

from app.services.travel_tool import (
    SearchRecommendationsArgs,
    ToolObservation,
    TravelTool,
    UpdateTripStateArgs,
)
from app.services.travel_tool_registry import TravelToolRegistry, UnknownTravelToolError


class _StubSearch:
    name = "search_recommendations"
    description = "stub search"
    def extract_args(self, decision): return SearchRecommendationsArgs(kind="accommodation", query=None)
    def run(self, args, context): return ToolObservation(summary="search: 0", data={})


class _StubUpdate:
    name = "update_trip_state"
    description = "stub update"
    def extract_args(self, decision): return UpdateTripStateArgs(decision=decision)
    def run(self, args, context): return ToolObservation(summary="update: ok", data={})


def test_registry_looks_up_tools_by_name() -> None:
    registry = TravelToolRegistry([_StubSearch(), _StubUpdate()])
    assert registry.get("search_recommendations").name == "search_recommendations"
    assert registry.get("update_trip_state").name == "update_trip_state"


def test_registry_rejects_unknown_tools() -> None:
    registry = TravelToolRegistry([_StubSearch()])
    with pytest.raises(UnknownTravelToolError):
        registry.get("replan_route")


def test_registry_describes_all_tools_for_prompts() -> None:
    registry = TravelToolRegistry([_StubSearch(), _StubUpdate()])
    description = registry.describe_for_prompt()
    assert "search_recommendations" in description
    assert "update_trip_state" in description


def test_registry_names_and_all_are_stable() -> None:
    registry = TravelToolRegistry([_StubSearch(), _StubUpdate()])
    assert set(registry.names()) == {"search_recommendations", "update_trip_state"}
    assert len(registry.all()) == 2
