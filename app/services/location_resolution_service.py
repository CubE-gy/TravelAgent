"""Map-backed confirmation of one user-entered location."""

import re
from typing import Protocol

from app.schemas.map import PoiCandidate, ResolvedLocation
from app.schemas.trip_state import LocationIntent, LocationResolutionStatus
from app.services.map_errors import MapNoResultsError, MapUpstreamError


class LocationMapService(Protocol):
    """The Stage 1 map facts required to confirm a location intent."""

    def search_pois(self, keyword: str, *, region: str | None = None) -> list[PoiCandidate]: ...

    def resolve_location(self, poi_id: str) -> ResolvedLocation: ...


def resolve_location_intent(
    location: LocationIntent,
    map_service: LocationMapService,
    *,
    region: str | None = None,
    auto_select: bool = False,
    city_name: str | None = None,
    field: str | None = None,
) -> LocationIntent:
    """Confirm one unresolved location or preserve its map ambiguity.

    Workspace callers can choose a strong match automatically. Other callers
    retain the original explicit-candidate confirmation behavior.
    """
    if location.resolution_status is not LocationResolutionStatus.UNRESOLVED:
        raise ValueError("only unresolved locations may be submitted for map resolution")

    candidates = map_service.search_pois(location.query, region=region)
    candidates = list({candidate.poi_id: candidate for candidate in candidates}.values())
    if auto_select and region:
        candidates = [candidate for candidate in candidates
                      if candidate.city_code is None or candidate.city_code == region]
    if not candidates:
        raise MapNoResultsError()
    selected = candidates[0] if len(candidates) == 1 else None
    if auto_select:
        selected = select_location_candidate(location.query, candidates, city_name=city_name, field=field)
    if selected is None and len(candidates) == 1:
        # A single unrelated hit is not evidence of the user's intended place.
        raise MapNoResultsError()
    if selected is None:
        return LocationIntent(
            query=location.query,
            resolution_status=LocationResolutionStatus.AMBIGUOUS,
            candidates=candidates,
        )

    resolved_location = map_service.resolve_location(selected.poi_id)
    if resolved_location.poi_id != selected.poi_id:
        raise MapUpstreamError()
    if auto_select and region and resolved_location.city_code not in (None, region):
        raise MapNoResultsError()
    return LocationIntent(
        query=location.query,
        resolution_status=LocationResolutionStatus.RESOLVED,
        resolved_location=resolved_location,
    )


def select_location_candidate(
    query: str, candidates: list[PoiCandidate], *, city_name: str | None, field: str | None,
) -> PoiCandidate | None:
    """Choose a clearly matching real POI; ties and weak matches need more context."""
    def normalize(name: str) -> str:
        name = re.sub(r"\s+", "", name).casefold()
        if city_name:
            for prefix in (city_name, city_name.removesuffix("市")):
                if prefix and name.startswith(prefix):
                    name = name[len(prefix):]
                    break
        return name

    keyword = normalize(query)
    if not keyword:
        return None
    scores: list[tuple[int, PoiCandidate]] = []
    ancillary = ("停车场", "售票处", "售票厅", "游客中心", "公共厕所", "卫生间", "公交站", "地铁站", "入口", "出口", "东门", "西门", "南门", "北门")
    suffixes = ("风景名胜区", "风景区", "景区", "博物院")
    for candidate in candidates:
        name = normalize(candidate.name)
        category = candidate.category_code or ""
        if any(word in name and word not in keyword for word in ancillary):
            continue
        if field == "accommodation" and category and not category.startswith("10"):
            continue
        if field == "places" and category.startswith(("05", "10", "1603")) and name != keyword:
            continue
        score = 100 if name == keyword else 0
        if not score:
            for suffix in suffixes:
                if name == keyword + suffix:
                    score = 95
                elif category.startswith("11") and name.endswith("-" + keyword + suffix):
                    score = 90
            if category.startswith("11") and name.endswith("-" + keyword):
                score = max(score, 90)
        # A unique result may use an official longer name, but it must still match.
        if len(candidates) == 1 and keyword in name:
            score = max(score, 80)
        # For a sightseeing intent, the visitor-facing scenic area is a better
        # match than the same-named lake/mountain's geographic center.
        if field == "places" and category.startswith("11") and score >= 80:
            score += 20
        scores.append((score, candidate))
    scores.sort(key=lambda item: item[0], reverse=True)
    if not scores or scores[0][0] < 80:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < 10:
        return None
    return scores[0][1]


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
