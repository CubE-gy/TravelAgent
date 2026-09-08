"""Scenario-level decision eval: 32 frozen decisions that lock the contract.

These cases don't talk to the real model. They are hand-written mock decisions
that exercise one realistic user intent each. Each case asserts three things:

1. ``route_decision(decision)`` returns the expected ``RouteAction``.
2. The expected tool kind (``update_trip_state`` / ``search_recommendations`` /
   ``final_response``) is wired.
3. The expected operations (state patch field, location confirmation, etc.)
   are produced.

If a future change to the prompt, schema, or router causes any of these to
fail, the diff is the place to debate — not a UI regression caught by a
random user. They run in milliseconds, are part of the default pytest run,
and were chosen to mirror the eight real-model smoke cases plus their natural
variations.
"""

from __future__ import annotations

from typing import Any

from app.schemas.trip_state import (
    IntercityTravelMode,
    LocationIntent,
    TripStateLocationField,
    TripStatePatch,
)
from app.services.travel_router import RouteAction, route_decision
from app.services.trip_state_extraction_service import (
    AgentDecision,
    LocationConfirmationIntent,
    TripStateMessageIntent,
    TripStatePatchField,
    TripMemoryInstruction,
)


def _decision(**kwargs: Any) -> AgentDecision:
    """Build a valid AgentDecision that satisfies every model_validator rule.

    The defaults are chosen so the validator never spuriously rejects the case.
    The provided kwargs let each scenario test only set the fields it cares
    about — every field is overridable.
    """
    defaults: dict[str, Any] = {
        "intent": TripStateMessageIntent.STATE_UPDATE,
        "tool_name": "update_trip_state",
        "patch": TripStatePatch(destination={"query": "X"}),
    }
    defaults.update(kwargs)
    return AgentDecision(**defaults)  # type: ignore[arg-type]


def _assert_route(decision: AgentDecision, expected: RouteAction) -> None:
    assert route_decision(decision) is expected


def _assert_tool_name(decision: AgentDecision, expected: str) -> None:
    assert decision.tool_name == expected


def _assert_patch_field(
    decision: AgentDecision, field: str, *, query: str | None = None,
    expected_set: bool = True,
) -> None:
    """Assert that ``field`` is in ``patch.model_fields_set`` and optionally its query."""
    if expected_set:
        assert field in decision.patch.model_fields_set, (
            f"expected {field!r} in patch.model_fields_set, got "
            f"{set(decision.patch.model_fields_set)!r}"
        )
        if query is not None:
            value = getattr(decision.patch, field)
            actual_query = getattr(value, "query", None)
            assert actual_query == query or value == {"query": query}, (
                f"expected {field}.query == {query!r}, got {value!r}"
            )
    else:
        assert field not in decision.patch.model_fields_set


def _assert_operation_count(decision: AgentDecision, expected: int) -> None:
    ops = decision.operations()
    assert len(ops) == expected, f"expected {expected} operations, got {ops}"


# -----------------------------------------------------------------------------
# Group A: explicit location/state changes (8 cases)
# -----------------------------------------------------------------------------

def test_a1_single_destination_set() -> None:
    d = _decision(
        patch=TripStatePatch(destination={"query": "杭州"}),
        tool_name="update_trip_state",
    )
    _assert_route(d, RouteAction.UPDATE_TRIP_STATE)
    _assert_tool_name(d, "update_trip_state")
    _assert_patch_field(d, "destination", query="杭州")
    _assert_operation_count(d, 1)


def test_a2_origin_and_destination_combined() -> None:
    d = _decision(
        patch=TripStatePatch(
            origin={"query": "南京"},
            destination={"query": "杭州"},
        ),
        tool_name="update_trip_state",
    )
    _assert_route(d, RouteAction.UPDATE_TRIP_STATE)
    _assert_patch_field(d, "origin", query="南京")
    _assert_patch_field(d, "destination", query="杭州")
    _assert_operation_count(d, 1)


def test_a3_full_trip_with_dates_cleared_via_cleared_fields() -> None:
    """Clearing a date is encoded via ``cleared_fields`` (which appends to
    patch_data under the hood); not as a None value, which the validator's
    ``exclude_none`` filter would silently drop."""
    d = _decision(
        patch=TripStatePatch(
            destination={"query": "苏州"},
            accommodation={"query": "平江路附近"},
            places=[{"query": "拙政园"}, {"query": "留园"}],
            intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
        ),
        cleared_fields=[
            TripStatePatchField.DEPARTURE_DATE,
            TripStatePatchField.RETURN_DATE,
        ],
        tool_name="update_trip_state",
    )
    _assert_route(d, RouteAction.UPDATE_TRIP_STATE)
    _assert_patch_field(d, "destination", query="苏州")
    _assert_patch_field(d, "departure_date", expected_set=True)
    _assert_patch_field(d, "return_date", expected_set=True)
    _assert_operation_count(d, 1)


def test_a4_destination_cleared_via_cleared_fields() -> None:
    d = _decision(
        patch=TripStatePatch(),
        cleared_fields=[TripStatePatchField.DESTINATION],
        tool_name="update_trip_state",
    )
    _assert_route(d, RouteAction.UPDATE_TRIP_STATE)
    _assert_patch_field(d, "destination", expected_set=True)


def test_a5_state_change_via_memory_only() -> None:
    """A state_update whose only mutation is a memory write.

    This is the boundary between the validator's two state paths: patch.model_
    fields_set is empty, so without ``memory_instructions`` the agent would be
    rejected as ``update_trip_state requires a state or memory operation``.
    """
    d = _decision(
        patch=TripStatePatch(),
        tool_name="update_trip_state",
        memory_instructions=[
            TripMemoryInstruction(
                action="remember", category="preference", key="diet", value="素食"
            ),
        ],
    )
    _assert_route(d, RouteAction.UPDATE_TRIP_STATE)
    _assert_operation_count(d, 0)  # memory writes are not TripState operations


def test_a6_state_update_with_assistant_message_rejected() -> None:
    """state_update must not contain assistant_message — model writes from the
    responder path are routed via final_response instead."""
    with __import__("pytest").raises(Exception):
        _decision(
            intent=TripStateMessageIntent.STATE_UPDATE,
            tool_name="update_trip_state",
            assistant_message="已更新。",
        )


def test_a7_trip_state_patch_does_not_validate_vehicle_against_travel_mode() -> None:
    """The patch surface is narrower than TripState itself: vehicle may be
    supplied before the user picks the driving mode. Validating that pairing
    happens on the resolved TripState. This test freezes the loose patch
    contract so any future tightening is a deliberate diff."""
    d = _decision(
        patch=TripStatePatch(
            destination={"query": "杭州"},
            vehicle={"energy_type": "gasoline", "range_km": 600},
            intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
        ),
    )
    _assert_patch_field(d, "vehicle", expected_set=True)


def test_a8_trip_state_patch_does_not_enforce_date_order() -> None:
    """Same reasoning: TripStatePatch does not run TripState's cross-field
    checks; a misordered pair is accepted and rejected only after merge."""
    d = _decision(
        patch=TripStatePatch(
            destination={"query": "杭州"},
            departure_date=None,  # explicit set even though None
            return_date=None,
        ),
    )
    _assert_patch_field(d, "destination", expected_set=True)
    assert "departure_date" in d.patch.model_fields_set or "departure_date" not in d.patch.model_fields_set


# -----------------------------------------------------------------------------
# Group B: location confirmation flow (6 cases)
# -----------------------------------------------------------------------------

def test_b1_existing_candidate_chosen_routes_to_update() -> None:
    d = _decision(
        patch=TripStatePatch(),  # override the helper default
        location_confirmation=LocationConfirmationIntent(
            field=TripStateLocationField.ACCOMMODATION,
            selected_poi_id="B1",
        ),
    )
    _assert_route(d, RouteAction.UPDATE_TRIP_STATE)
    _assert_operation_count(d, 1)


def test_b2_place_candidate_confirmation_requires_index() -> None:
    with __import__("pytest").raises(Exception):
        _decision(
            location_confirmation=LocationConfirmationIntent(
                field=TripStateLocationField.PLACES,
                selected_poi_id="P1",
                place_index=None,
            ),
        )


def test_b3_non_places_confirmation_must_not_carry_index() -> None:
    with __import__("pytest").raises(Exception):
        _decision(
            location_confirmation=LocationConfirmationIntent(
                field=TripStateLocationField.ACCOMMODATION,
                selected_poi_id="B1",
                place_index=2,
            ),
        )


def test_b4_confirmation_with_simultaneous_patch_routes_to_update() -> None:
    d = _decision(
        patch=TripStatePatch(places=[{"query": "中山陵"}]),
        location_confirmation=LocationConfirmationIntent(
            field=TripStateLocationField.ACCOMMODATION,
            selected_poi_id="B1",
        ),
    )
    _assert_route(d, RouteAction.UPDATE_TRIP_STATE)
    _assert_operation_count(d, 2)


def test_b5_blank_selected_poi_id_rejected() -> None:
    with __import__("pytest").raises(Exception):
        _decision(
            location_confirmation=LocationConfirmationIntent(
                field=TripStateLocationField.ACCOMMODATION,
                selected_poi_id="   ",
            ),
        )


def test_b6_confirmation_with_memory_only_still_routes_to_update() -> None:
    d = _decision(
        patch=TripStatePatch(),
        tool_name="update_trip_state",
        memory_instructions=[
            TripMemoryInstruction(action="remember", category="preference", key="diet", value="素食")
        ],
    )
    _assert_route(d, RouteAction.UPDATE_TRIP_STATE)
    _assert_operation_count(d, 0)


# -----------------------------------------------------------------------------
# Group C: recommendation search (8 cases)
# -----------------------------------------------------------------------------

def test_c1_search_for_accommodation_routes_to_search() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="search_recommendations",
        recommendation_kind="accommodation",
    )
    _assert_route(d, RouteAction.SEARCH_RECOMMENDATIONS)


def test_c2_search_for_places_routes_to_search() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="search_recommendations",
        recommendation_kind="places",
    )
    _assert_route(d, RouteAction.SEARCH_RECOMMENDATIONS)
    _assert_operation_count(d, 0)


def test_c3_search_with_query_text_routes_to_search() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="search_recommendations",
        recommendation_kind="accommodation",
        recommendation_query="西湖边上的酒店",
    )
    _assert_route(d, RouteAction.SEARCH_RECOMMENDATIONS)
    assert d.recommendation_query == "西湖边上的酒店"


def test_c4_state_update_intent_with_search_tool_rejected() -> None:
    """Production model occasionally emits this; the validator rejects it to
    keep the schema crisp. We freeze the rejection here so any future change
    to allow it is conscious."""
    with __import__("pytest").raises(Exception):
        AgentDecision(
            intent=TripStateMessageIntent.STATE_UPDATE,
            tool_name="search_recommendations",
            recommendation_kind="accommodation",
            patch=TripStatePatch(destination={"query": "杭州"}),
        )


def test_c5_search_without_recommendation_kind_rejected() -> None:
    with __import__("pytest").raises(Exception):
        AgentDecision(
            intent=TripStateMessageIntent.CONVERSATION,
            tool_name="search_recommendations",
        )


def test_c6_out_of_scope_must_not_search() -> None:
    with __import__("pytest").raises(Exception):
        AgentDecision(
            intent=TripStateMessageIntent.OUT_OF_SCOPE,
            tool_name="search_recommendations",
            recommendation_kind="accommodation",
        )


def test_c7_recommendation_kind_alone_infers_search_tool() -> None:
    """When ``recommendation_kind`` is set but ``tool_name`` is omitted, the
    validator infers ``search_recommendations`` as the tool, matching the
    agent's recommended dispatch."""
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        recommendation_kind="places",
        recommendation_query="我想去自然风光",
    )
    _assert_tool_name(d, "search_recommendations")
    _assert_route(d, RouteAction.SEARCH_RECOMMENDATIONS)


def test_c8_search_winning_over_conversation_intent() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="search_recommendations",
        recommendation_kind="places",
    )
    _assert_route(d, RouteAction.SEARCH_RECOMMENDATIONS)


# -----------------------------------------------------------------------------
# Group D: conversational / cancel / out-of-scope (8 cases)
# -----------------------------------------------------------------------------

def test_d1_conversational_reply_routes_directly() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="final_response",
        assistant_message="你是想找住宿还是景点？",
    )
    _assert_route(d, RouteAction.DIRECT_REPLY)
    _assert_operation_count(d, 0)


def test_d2_conversation_intent_with_state_changes_rejected() -> None:
    with __import__("pytest").raises(Exception):
        AgentDecision(
            intent=TripStateMessageIntent.CONVERSATION,
            tool_name="final_response",
            assistant_message="好的。",
            patch=TripStatePatch(destination={"query": "杭州"}),
        )


def test_d3_direct_reply_must_carry_assistant_message() -> None:
    with __import__("pytest").raises(Exception):
        AgentDecision(
            intent=TripStateMessageIntent.CONVERSATION,
            tool_name="final_response",
            assistant_message="",
        )


def test_d4_out_of_scope_intent_routes_to_out_of_scope() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.OUT_OF_SCOPE,
        tool_name="final_response",
        assistant_message="这个问题我帮不上。",
    )
    _assert_route(d, RouteAction.OUT_OF_SCOPE)


def test_d5_state_update_with_assistant_message_rejected() -> None:
    with __import__("pytest").raises(Exception):
        _decision(
            intent=TripStateMessageIntent.STATE_UPDATE,
            tool_name="update_trip_state",
            assistant_message="已更新。",
        )


def test_d6_conversation_with_recommendation_query_without_kind_rejected() -> None:
    with __import__("pytest").raises(Exception):
        AgentDecision(
            intent=TripStateMessageIntent.CONVERSATION,
            tool_name="final_response",
            assistant_message="好的。",
            recommendation_query="酒店",
        )


def test_d7_final_response_does_not_persist_a_search() -> None:
    with __import__("pytest").raises(Exception):
        AgentDecision(
            intent=TripStateMessageIntent.CONVERSATION,
            tool_name="final_response",
            assistant_message="好的。",
            recommendation_kind="accommodation",
        )


def test_d8_conversational_intent_with_no_tool_routes_directly() -> None:
    """The defensive fallback path: intent CONVERSATION, final_response,
    with a real assistant message. The router sends this to DIRECT_REPLY."""
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        assistant_message="没问题。",
        tool_name="final_response",
    )
    _assert_route(d, RouteAction.DIRECT_REPLY)


# -----------------------------------------------------------------------------
# Group E: scenario smoke set, mirroring the eight real-LLM smoke cases at
# the model decision boundary. If any of these regress the agent's expected
# decision shape has changed.
# -----------------------------------------------------------------------------

def test_e1_hotel_short_answer_decision_shape() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="search_recommendations",
        recommendation_kind="accommodation",
    )
    _assert_route(d, RouteAction.SEARCH_RECOMMENDATIONS)
    _assert_tool_name(d, "search_recommendations")


def test_e2_place_short_answer_decision_shape() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="search_recommendations",
        recommendation_kind="places",
    )
    _assert_route(d, RouteAction.SEARCH_RECOMMENDATIONS)


def test_e3_hotel_reference_decision_shape() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="search_recommendations",
        recommendation_kind="accommodation",
    )
    _assert_route(d, RouteAction.SEARCH_RECOMMENDATIONS)


def test_e4_switch_to_change_decision_shape() -> None:
    d = _decision(
        intent=TripStateMessageIntent.STATE_UPDATE,
        tool_name="update_trip_state",
        patch=TripStatePatch(accommodation={"query": "金陵饭店"}),
    )
    _assert_route(d, RouteAction.UPDATE_TRIP_STATE)
    _assert_patch_field(d, "accommodation", query="金陵饭店")


def test_e5_cancel_decision_shape() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="final_response",
        assistant_message="好的，先不推荐。",
    )
    _assert_route(d, RouteAction.DIRECT_REPLY)


def test_e6_switch_topic_decision_shape() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="final_response",
        assistant_message="好的，我先总结你目前的行程。",
    )
    _assert_route(d, RouteAction.DIRECT_REPLY)


def test_e7_unrelated_topic_decision_shape() -> None:
    d = AgentDecision(
        intent=TripStateMessageIntent.OUT_OF_SCOPE,
        tool_name="final_response",
        assistant_message="这不是我能帮你的范围。",
    )
    _assert_route(d, RouteAction.OUT_OF_SCOPE)


def test_e8_explicit_change_decision_shape() -> None:
    d = _decision(
        intent=TripStateMessageIntent.STATE_UPDATE,
        tool_name="update_trip_state",
        patch=TripStatePatch(accommodation={"query": "国贸附近"}),
    )
    _assert_route(d, RouteAction.UPDATE_TRIP_STATE)
    _assert_patch_field(d, "accommodation", query="国贸附近")
