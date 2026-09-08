"""One-row decision table that maps a validated AgentDecision to a route action.

The Agent model already produces an explicit ``tool_name`` (update_trip_state /
search_recommendations / final_response) plus an explicit ``intent`` (state_update /
conversation / out_of_scope). This module centralises how those axes collapse into
the four runtime routes that the conversation service cares about. Keeping this
mapping in one place means callers never branch on ``decision.tool_name``
directly and Stage 5/6 can extend the table without touching the Agent service.
"""

from __future__ import annotations

from enum import StrEnum

from app.services.trip_state_extraction_service import (
    AgentDecision,
    TripStateMessageIntent,
)


class RouteAction(StrEnum):
    """The four execution routes a Travel Manager turn may take."""

    UPDATE_TRIP_STATE = "update_trip_state"
    SEARCH_RECOMMENDATIONS = "search_recommendations"
    DIRECT_REPLY = "direct_reply"
    OUT_OF_SCOPE = "out_of_scope"


def route_decision(decision: AgentDecision) -> RouteAction:
    """Return the single route this turn should be dispatched through."""
    intent = decision.intent

    # Out-of-scope always wins — it never carries travel operations and never
    # warrants a map search.
    if intent is TripStateMessageIntent.OUT_OF_SCOPE:
        return RouteAction.OUT_OF_SCOPE

    # A request to pull a candidate list from the map is the most specific
    # signal: if the agent asked for candidates, route them to the search path
    # regardless of any auxiliary intent metadata it may have produced.
    if decision.recommendation_kind is not None:
        return RouteAction.SEARCH_RECOMMENDATIONS

    # Pure conversational turns only ever become a direct reply — a request
    # marked "update" without any patch/confirmation/memory is rejected by the
    # AgentDecision model validator, so it cannot reach this branch.
    if intent is TripStateMessageIntent.CONVERSATION:
        return RouteAction.DIRECT_REPLY

    # Intent is STATE_UPDATE at this point. The agent's validated ``tool_name``
    # is the authoritative dispatch signal, so we only trust known values.
    tool = decision.tool_name
    if tool == "update_trip_state":
        return RouteAction.UPDATE_TRIP_STATE
    if tool == "search_recommendations":
        return RouteAction.SEARCH_RECOMMENDATIONS
    if tool == "final_response":
        return RouteAction.DIRECT_REPLY

    # Default: state_update without a recognised tool name is rejected upstream,
    # but be defensive so callers never crash on a shape change in the schema.
    return RouteAction.DIRECT_REPLY
