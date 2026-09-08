"""The two travel tools a Travel Manager turn may dispatch through the registry.

A tool is a small, typed executor. The LLM never touches it directly: the
manager agent parses the validated decision, looks up the tool by name, and
hands it a typed args struct plus a session-scoped context. The tool returns
a structured ``ToolObservation`` that is fed back to the reply model.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.schemas.trip_state import TripState
from app.schemas.trip_recommendation import RecommendationKind
from app.services.trip_state_extraction_service import AgentDecision
from app.services.trip_state_update_service import TripStateUpdateService
from app.services.trip_recommendation_service import TripRecommendationService


@dataclass(frozen=True)
class ToolContext:
    """The bounded, immutable context a tool runs within."""

    session: Session
    trip_id: UUID
    current_state: TripState
    expected_revision: int


@dataclass(frozen=True)
class ToolObservation:
    """A tool's structured outcome, with a trace summary and a model-facing payload."""

    summary: str
    data: dict[str, Any] = field(default_factory=dict)


class UpdateTripStateArgs(BaseModel):
    """Pass-through args: the validated decision that the updater will apply."""

    decision: AgentDecision


class SearchRecommendationsArgs(BaseModel):
    """The narrow inputs the map search actually needs."""

    kind: RecommendationKind
    query: str | None = Field(default=None, max_length=80)


class TravelTool(ABC):
    """One executable step the LLM may select through the registry."""

    name: str
    description: str

    @abstractmethod
    def extract_args(self, decision: AgentDecision) -> BaseModel:
        """Pick the tool's own arguments out of the validated decision."""

    @abstractmethod
    def run(self, args: BaseModel, context: ToolContext) -> ToolObservation:
        """Run the tool within the given session, returning a structured outcome."""


class UpdateTripStateTool(TravelTool):
    """Apply the decision's state, memory, and location-confirmation operations."""

    name = "update_trip_state"
    description = (
        "Apply the validated state, memory, or location-confirmation operations the model decided on. "
        "Returns the new state revision, the operations that ran, and any location lookup failures."
    )

    def __init__(self, updater: TripStateUpdateService) -> None:
        self._updater = updater

    def extract_args(self, decision: AgentDecision) -> UpdateTripStateArgs:
        if decision.intent.value != "state_update":
            raise ValueError("update_trip_state requires a state_update decision")
        return UpdateTripStateArgs(decision=decision)

    def run(self, args: BaseModel, context: ToolContext) -> ToolObservation:
        update_args = args  # type: UpdateTripStateArgs
        result = self._updater.execute_decision(
            context.session, context.trip_id, context.current_state, update_args.decision,
            expected_revision=context.expected_revision, commit=False,
        )
        return ToolObservation(
            summary=(
                f"update_trip_state: revision {context.current_state.revision} -> {result.state.revision}"
            ),
            data={
                "state": result.state.model_dump(mode="json"),
                "state_revision": result.state.revision,
                "location_failures": [failure.__dict__ for failure in result.location_failures],
                "executed_operations": [
                    operation.kind.value for operation in update_args.decision.operations()
                ],
                "memory_instructions": [
                    instruction.action for instruction in update_args.decision.memory_instructions
                ],
            },
        )


class SearchRecommendationsTool(TravelTool):
    """Map-backed POI search around the destination, never mutating TripState."""

    name = "search_recommendations"
    description = (
        "Search the map near the destination city for accommodation or places. "
        "Never mutates TripState. Returns the verified candidates and a session id; "
        "the model can describe those candidates in its reply."
    )

    def __init__(self, service: TripRecommendationService) -> None:
        self._service = service

    def extract_args(self, decision: AgentDecision) -> SearchRecommendationsArgs:
        if decision.recommendation_kind is None:
            raise ValueError("search_recommendations requires recommendation_kind")
        return SearchRecommendationsArgs(
            kind=decision.recommendation_kind,
            query=decision.recommendation_query,
        )

    def run(self, args: BaseModel, context: ToolContext) -> ToolObservation:
        search_args = args  # type: SearchRecommendationsArgs
        session_id, recommendations = self._service.create_session(
            context.session, context.trip_id, context.current_state, search_args.kind,
            keyword=search_args.query,
        )
        return ToolObservation(
            summary=(
                f"search_recommendations: {search_args.kind} returned {len(recommendations)} candidates"
            ),
            data={
                "kind": search_args.kind,
                "query": search_args.query,
                "session_id": str(session_id),
                "candidates": [
                    {
                        "poi_id": rec.location.poi_id,
                        "name": rec.location.name,
                        "address": rec.location.address,
                        "category": rec.location.category_name,
                        "coordinate": rec.location.coordinate,
                    }
                    for rec in recommendations
                ],
            },
        )
