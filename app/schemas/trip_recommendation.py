"""Transient map-backed recommendations and their explicit selection request."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.base import ApiRequest
from app.schemas.map import ResolvedLocation


RecommendationKind = Literal["accommodation", "places"]


class TripRecommendationRead(BaseModel):
    """One real POI offered only for the current conversation response."""

    kind: RecommendationKind
    location: ResolvedLocation


class TripRecommendationContext(BaseModel):
    """A server-owned pending recommendation set referenced by the browser."""

    recommendation_session_id: UUID


class TripRecommendationSelection(ApiRequest):
    """An explicit click on a transient recommendation card."""

    kind: RecommendationKind
    poi_id: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=0)
    recommendation_session_id: UUID | None = None
