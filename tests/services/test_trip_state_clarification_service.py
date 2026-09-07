from uuid import uuid4

import pytest

from app.models.enums import IntercityTravelMode, TravelMode
from app.schemas.trip_state import TripState
from app.schemas.trip_state_clarification import (
    ClarificationQuestion,
    TripStateClarification,
)
from app.services.llm_provider import LlmMessage, LlmProvider, LlmResponseError
from app.services.trip_state_assessor import assess_trip_state
from app.services.trip_state_clarification_service import TripStateClarificationService
from app.services.trip_state_location_resolution_service import LocationResolutionFailure
from app.services.trip_state_update_service import TripStateUpdateResult


class FakeClarificationProvider:
    def __init__(self, result: TripStateClarification) -> None:
        self.result = result
        self.calls: list[tuple[list[LlmMessage], type[TripStateClarification]]] = []

    def generate_structured(
        self,
        messages: list[LlmMessage],
        response_model: type[TripStateClarification],
    ) -> TripStateClarification:
        self.calls.append((messages, response_model))
        return self.result


def update_result(
    state: TripState,
    failures: list[LocationResolutionFailure] | None = None,
) -> TripStateUpdateResult:
    return TripStateUpdateResult(
        state=state,
        location_failures=failures or [],
        assessment=assess_trip_state(state),
    )


def resolved_location(query: str, poi_id: str) -> dict[str, object]:
    return {
        "query": query,
        "resolution_status": "resolved",
        "resolved_location": {
            "poi_id": poi_id,
            "name": query,
            "coordinate": {"latitude": 39.9, "longitude": 116.4},
        },
    }


def complete_state(**changes: object) -> TripState:
    state_data: dict[str, object] = {
        "trip_id": uuid4(),
        "origin": resolved_location("南京", "B000O1"),
        "destination": resolved_location("北京", "B000D1"),
        "return_destination": resolved_location("南京", "B000R1"),
        "departure_date": "2026-10-01",
        "return_date": "2026-10-03",
        "accommodation": resolved_location("王府井", "B000H1"),
        "places": [resolved_location("故宫", "B000P1")],
        "intercity_travel_mode": IntercityTravelMode.HIGH_SPEED_RAIL,
        "local_travel_mode": TravelMode.PUBLIC_TRANSPORT,
    }
    state_data.update(changes)
    return TripState.model_validate(state_data)


def test_generate_asks_only_for_missing_planning_fields() -> None:
    provider = FakeClarificationProvider(
        TripStateClarification(
            questions=[
                ClarificationQuestion(topic_id="missing:origin", question="从哪里出发？"),
                ClarificationQuestion(topic_id="missing:destination", question="这趟旅行去哪里？"),
                ClarificationQuestion(topic_id="missing:return_destination", question="最终返回哪里？"),
                ClarificationQuestion(topic_id="missing:departure_date", question="哪天出发？"),
                ClarificationQuestion(topic_id="missing:return_date", question="哪天返程？"),
                ClarificationQuestion(topic_id="missing:accommodation", question="住在哪里？"),
                ClarificationQuestion(topic_id="missing:places", question="想去哪些地点？"),
                ClarificationQuestion(topic_id="missing:intercity_travel_mode", question="城际怎么去？"),
                ClarificationQuestion(topic_id="missing:local_travel_mode", question="当地怎么出行？"),
            ]
        )
    )

    clarification = TripStateClarificationService(provider).generate(
        update_result(TripState(trip_id=uuid4()))
    )

    assert isinstance(provider, LlmProvider)
    assert clarification.questions[0].question == "从哪里出发？"
    messages, response_model = provider.calls[0]
    assert response_model is TripStateClarification
    assert "Do not recommend destinations" in messages[0].content
    assert '"topic_id":"missing:vehicle"' not in messages[1].content


def test_generate_provides_ambiguous_candidates_for_confirmation() -> None:
    state = complete_state(
        accommodation={
            "query": "万达广场",
            "resolution_status": "ambiguous",
            "candidates": [
                {"poi_id": "B000H1", "name": "北京万达广场", "coordinate": {"latitude": 39.9, "longitude": 116.4}},
                {"poi_id": "B000H2", "name": "上海万达广场", "coordinate": {"latitude": 31.2, "longitude": 121.5}},
            ],
        },
    )
    provider = FakeClarificationProvider(
        TripStateClarification(
            questions=[
                ClarificationQuestion(
                    topic_id="confirm:accommodation",
                    question="请在北京万达广场和上海万达广场中选择住宿地点。",
                )
            ]
        )
    )

    clarification = TripStateClarificationService(provider).generate(update_result(state))

    assert clarification.questions[0].topic_id == "confirm:accommodation"
    assert "B000H1" in provider.calls[0][0][1].content
    assert "B000H2" in provider.calls[0][0][1].content


def test_generate_refines_location_when_map_lookup_failed() -> None:
    state = complete_state(destination={"query": "不存在的城市"})
    provider = FakeClarificationProvider(
        TripStateClarification(
            questions=[
                ClarificationQuestion(topic_id="refine:destination", question="请提供更具体的目的地名称或地址。"),
            ]
        )
    )
    failure = LocationResolutionFailure(
        field="destination",
        query="不存在的城市",
        error_code="map_no_results",
    )

    clarification = TripStateClarificationService(provider).generate(update_result(state, [failure]))

    assert clarification.questions[-1].topic_id == "refine:destination"
    assert "map_no_results" in provider.calls[0][0][1].content


def test_generate_skips_llm_when_state_is_ready() -> None:
    state = complete_state()
    provider = FakeClarificationProvider(TripStateClarification())

    clarification = TripStateClarificationService(provider).generate(update_result(state))

    assert clarification.questions == []
    assert provider.calls == []


def test_generate_rejects_missing_duplicate_or_unknown_topics() -> None:
    provider = FakeClarificationProvider(
        TripStateClarification(
            questions=[
                ClarificationQuestion(topic_id="missing:destination", question="去哪里？"),
                ClarificationQuestion(topic_id="missing:destination", question="住哪里？"),
            ]
        )
    )

    with pytest.raises(LlmResponseError, match="do not match"):
        TripStateClarificationService(provider).generate(update_result(TripState(trip_id=uuid4())))


def test_workspace_does_not_require_dates_hotels_transport_or_return_before_showing_map():
    state = TripState(trip_id=uuid4(), destination=resolved_location("南京", "city-old"))
    provider = FakeClarificationProvider(TripStateClarification())
    assert TripStateClarificationService(provider, workspace_mode=True).generate(update_result(state)).questions == []
    assert provider.calls == []


def test_workspace_timeout_does_not_ask_for_more_address_details():
    state = TripState(trip_id=uuid4(), destination={"query": "南京"})
    provider = FakeClarificationProvider(TripStateClarification())
    result = update_result(state, [LocationResolutionFailure(field="destination", query="南京", error_code="map_timeout")])
    assert TripStateClarificationService(provider, workspace_mode=True).generate(result).questions == []
    assert provider.calls == []
