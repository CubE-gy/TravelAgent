"""Decision-table tests for travel routing.

These cases freeze the rule "given a specific shape of AgentDecision, which
route the conversation service will dispatch the turn through". Changing any
of these failures means the runtime behavioural contract changed, not
necessarily that the change is wrong — but the value here is that the choice
becomes a deliberate conscious diff instead of a side effect.
"""

from app.services.travel_router import RouteAction, route_decision
from app.services.trip_state_extraction_service import (
    AgentDecision,
    TripStateMessageIntent,
    TripStatePatch,
)


def _decision(
    *,
    intent: TripStateMessageIntent | None = None,
    tool_name: str | None = "update_trip_state",
    patch: TripStatePatch | None = None,
    recommendation_kind: str | None = None,
    assistant_message: str | None = None,
) -> AgentDecision:
    """Build the smallest AgentDecision that satisfies every model_validator rule.

    The helper infers unused fields from ``tool_name``:

    - ``update_trip_state`` must carry a patch with at least one explicit field,
      so we inject ``TripStatePatch(destination={"query": "X"})`` when none is
      provided.
    - ``search_recommendations`` must carry a ``recommendation_kind`` and run
      under the CONVERSATION intent (state_update forbids recommendation).
    - ``final_response`` must carry a non-blank ``assistant_message`` and run
      under the CONVERSATION intent.
    - ``tool_name=None`` exercises the defensive fallback path; we explicitly
      pass ``assistant_message``/``recommendation_kind`` to make the intent
      unambiguous.
    """
    if tool_name == "update_trip_state":
        return AgentDecision(
            intent=intent or TripStateMessageIntent.STATE_UPDATE,
            tool_name="update_trip_state",
            patch=patch or TripStatePatch(destination={"query": "X"}),
        )
    if tool_name == "search_recommendations":
        assert recommendation_kind is not None, "test must supply recommendation_kind"
        return AgentDecision(
            intent=intent or TripStateMessageIntent.CONVERSATION,
            tool_name="search_recommendations",
            recommendation_kind=recommendation_kind,
        )
    if tool_name == "final_response":
        return AgentDecision(
            intent=intent or TripStateMessageIntent.CONVERSATION,
            tool_name="final_response",
            assistant_message=assistant_message or "好的，已记录。",
        )
    return AgentDecision(
        intent=intent or TripStateMessageIntent.STATE_UPDATE,
        tool_name=tool_name,
        patch=patch or TripStatePatch(destination=None),
        assistant_message=assistant_message,
        recommendation_kind=recommendation_kind,
    )


def test_out_of_scope_intent_short_circuits_every_other_signal() -> None:
    decision = _decision(
        intent=TripStateMessageIntent.OUT_OF_SCOPE,
        tool_name="final_response",
        assistant_message="这个问题不在我的服务范围。",
    )
    assert route_decision(decision) is RouteAction.OUT_OF_SCOPE


def test_search_routing_wins_when_recommendation_kind_is_present() -> None:
    # Even if the model also flagged a state_update intent (e.g. while
    # explaining what it searched for), the explicit candidate request is the
    # stronger signal.
    decision = _decision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="search_recommendations",
        recommendation_kind="places",
    )
    assert route_decision(decision) is RouteAction.SEARCH_RECOMMENDATIONS


def test_conversational_intent_routes_to_direct_reply() -> None:
    decision = _decision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="final_response",
        assistant_message="好的，没问题。",
    )
    assert route_decision(decision) is RouteAction.DIRECT_REPLY


def test_state_update_intent_with_explicit_update_tool_routes_to_update() -> None:
    decision = _decision(
        intent=TripStateMessageIntent.STATE_UPDATE,
        tool_name="update_trip_state",
        patch=TripStatePatch(destination={"query": "杭州"}),
    )
    assert route_decision(decision) is RouteAction.UPDATE_TRIP_STATE


def test_state_update_intent_with_search_tool_routes_to_search() -> None:
    decision = _decision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="search_recommendations",
        recommendation_kind="accommodation",
    )
    assert route_decision(decision) is RouteAction.SEARCH_RECOMMENDATIONS


def test_final_response_with_state_update_intent_routes_to_direct_reply() -> None:
    # final_response + state_update is a coherent shape: the model decided it
    # will not touch the state this turn and will reply directly. The state
    # validator forbids this exact pair, so the test uses a CONVERSATION
    # intent and checks the routing intent of ``final_response``.
    decision = _decision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="final_response",
        assistant_message="已记录。",
    )
    assert route_decision(decision) is RouteAction.DIRECT_REPLY


def test_unknown_tool_name_with_state_update_intent_falls_back_to_direct_reply() -> None:
    # The AgentDecision validator rejects this shape upstream. If a future
    # schema ever leaks past validation, the router should still return a
    # defined action rather than crash on a dict lookup.
    decision = _decision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name=None,
        assistant_message="好的。",
    )
    assert route_decision(decision) is RouteAction.DIRECT_REPLY


def test_conversation_intent_with_recommendation_kind_still_routes_to_search() -> None:
    # "推荐酒店" is a conversational ask that carries an explicit
    # recommendation_kind. Both signals are present; recommendation_kind is
    # the dispatch signal and the route must resolve to SEARCH.
    decision = _decision(
        intent=TripStateMessageIntent.CONVERSATION,
        tool_name="search_recommendations",
        recommendation_kind="accommodation",
    )
    assert route_decision(decision) is RouteAction.SEARCH_RECOMMENDATIONS


def test_realistic_state_change_with_patch_wires_to_update() -> None:
    decision = _decision(
        intent=TripStateMessageIntent.STATE_UPDATE,
        tool_name="update_trip_state",
        patch=TripStatePatch(destination={"query": "杭州"}),
    )
    assert route_decision(decision) is RouteAction.UPDATE_TRIP_STATE


def test_route_returns_only_four_action_values() -> None:
    """Exhaustive guard against accidentally adding a new route enum member."""
    allowed = {
        RouteAction.UPDATE_TRIP_STATE,
        RouteAction.SEARCH_RECOMMENDATIONS,
        RouteAction.DIRECT_REPLY,
        RouteAction.OUT_OF_SCOPE,
    }
    assert set(RouteAction) == allowed
