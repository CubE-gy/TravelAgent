"""Map-backed confirmation of one user-entered location."""

from typing import Protocol

from app.schemas.map import PoiCandidate, ResolvedLocation
from app.schemas.trip_state import LocationIntent, LocationResolutionStatus


class LocationMapService(Protocol):
    """The Stage 1 map facts required to confirm a location intent."""

    def search_pois(self, keyword: str, *, region: str | None = None) -> list[PoiCandidate]: ...

    def resolve_location(self, poi_id: str) -> ResolvedLocation: ...


def resolve_location_intent(
    location: LocationIntent,
    map_service: LocationMapService,
    *,
    region: str | None = None,
) -> LocationIntent:
    """Confirm one unresolved location or preserve its map ambiguity.

    A single Amap candidate is confirmed through its detail endpoint. Multiple
    candidates are deliberately kept for the user to choose from.
    """
    if location.resolution_status is not LocationResolutionStatus.UNRESOLVED:
        raise ValueError("only unresolved locations may be submitted for map resolution")

    candidates = map_service.search_pois(location.query, region=region)
    if len(candidates) > 1:
        return LocationIntent(
            query=location.query,
            resolution_status=LocationResolutionStatus.AMBIGUOUS,
            candidates=candidates,
        )

    resolved_location = map_service.resolve_location(candidates[0].poi_id)
    return LocationIntent(
        query=location.query,
        resolution_status=LocationResolutionStatus.RESOLVED,
        resolved_location=resolved_location,
    )


def confirm_location_candidate(
    location: LocationIntent,
    selected_poi_id: str,
    map_service: LocationMapService,
) -> LocationIntent:
    """Confirm one user-selected candidate from an ambiguous location."""
    if location.resolution_status is not LocationResolutionStatus.AMBIGUOUS:
        raise ValueError("only ambiguous locations may have a candidate confirmed")

    normalized_poi_id = selected_poi_id.strip()
    if not normalized_poi_id:
        raise ValueError("selected_poi_id must not be blank")
    if not any(candidate.poi_id == normalized_poi_id for candidate in location.candidates):
        raise ValueError("selected_poi_id must belong to the location candidates")

    resolved_location = map_service.resolve_location(normalized_poi_id)
    return LocationIntent(
        query=location.query,
        resolution_status=LocationResolutionStatus.RESOLVED,
        resolved_location=resolved_location,
    )
