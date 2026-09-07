"""Map-fact recommendations that never become Trip memory until clicked."""

from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories.trip_recommendation_session import (
    get_active_recommendation_session, replace_active_recommendation_session,
)
from app.repositories.trip import sync_trip_dates_from_state
from app.repositories.trip_state import save_trip_state
from app.schemas.map import GeoPoint, PoiCandidate, ResolvedLocation
from app.schemas.trip_recommendation import RecommendationKind, TripRecommendationRead
from app.schemas.trip_state import LocationIntent, TripState, TripStatePatch
from app.services.trip_state_assessor import assess_trip_state
from app.services.trip_state_merger import merge_trip_state
from app.services.trip_state_update_service import TripStateUpdateResult


class RecommendationMapService(Protocol):
    def search_nearby_pois(
        self, center: GeoPoint, *, keyword: str | None = None, types: str | None = None,
        radius_meters: int = 5000,
    ) -> list[PoiCandidate]: ...

    def resolve_location(self, poi_id: str) -> ResolvedLocation: ...


class TripRecommendationService:
    """Search real nearby POIs and persist only an explicit user click."""

    _TYPES = {"accommodation": "100000", "places": "110000"}

    def __init__(self, map_service: RecommendationMapService) -> None:
        self._map_service = map_service

    def recommend(
        self, state: TripState, kind: RecommendationKind, *, keyword: str | None = None,
    ) -> list[TripRecommendationRead]:
        destination = state.destination
        if destination is None or destination.resolved_city is None:
            return []
        city = destination.resolved_city
        candidates = self._map_service.search_nearby_pois(
            city.center, keyword=keyword, types=self._TYPES[kind], radius_meters=5000
        )
        results: list[TripRecommendationRead] = []
        for candidate in candidates:
            if candidate.city_code not in (None, city.city_code):
                continue
            location = self._map_service.resolve_location(candidate.poi_id)
            if location.city_code not in (None, city.city_code):
                continue
            results.append(TripRecommendationRead(kind=kind, location=location))
            if len(results) == 4:
                break
        return results

    def create_session(
        self, session: Session, trip_id: UUID, state: TripState, kind: RecommendationKind,
        *, keyword: str | None = None,
    ) -> tuple[UUID, list[TripRecommendationRead]]:
        """Run a map search and retain exactly its verified candidates on the server."""
        recommendations = self.recommend(state, kind, keyword=keyword)
        record = replace_active_recommendation_session(
            session, trip_id, kind=kind, query=keyword,
            candidates=[item.model_dump(mode="json") for item in recommendations],
            state_revision=state.revision,
        )
        return record.id, recommendations

    def select(
        self, session: Session, trip_id: UUID, state: TripState, *, kind: RecommendationKind,
        poi_id: str, expected_revision: int,
        recommendation_session_id: UUID | None = None,
    ) -> TripStateUpdateResult:
        if state.revision != expected_revision:
            from app.repositories.trip_state import TripStateRevisionConflictError
            raise TripStateRevisionConflictError(expected_revision, state.revision)
        destination = state.destination
        if destination is None or destination.resolved_city is None:
            raise ValueError("destination city must be confirmed before selecting a recommendation")
        if recommendation_session_id is not None:
            recommendation = get_active_recommendation_session(session, trip_id, recommendation_session_id)
            if recommendation is None or recommendation.kind != kind:
                raise ValueError("recommendation session is no longer active")
            candidate_ids = {item["location"]["poi_id"] for item in recommendation.candidates}
            if poi_id not in candidate_ids:
                raise ValueError("selected POI is not in the active recommendation session")
        location = self._map_service.resolve_location(poi_id)
        if location.city_code not in (None, destination.resolved_city.city_code):
            raise ValueError("recommended POI must belong to the destination city")
        intent = LocationIntent(
            query=location.name, resolution_status="resolved", resolved_location=location
        )
        patch = TripStatePatch(**(
            {"accommodation": intent}
            if kind == "accommodation"
            else {"places": [*state.places, intent]}
        ))
        updated = merge_trip_state(state, patch)
        persisted = save_trip_state(session, updated, expected_revision=expected_revision)
        sync_trip_dates_from_state(
            session, trip_id, start_date=persisted.departure_date, end_date=persisted.return_date
        )
        return TripStateUpdateResult(
            state=persisted, location_failures=[], assessment=assess_trip_state(persisted),
            executed_tools=True,
        )
