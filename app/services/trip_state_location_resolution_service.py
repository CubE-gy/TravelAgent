"""Batch Amap confirmation for the locations contained in one TripState."""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.models.enums import IntercityTravelMode
from app.schemas.map import ResolvedCity
from app.schemas.trip_state import LocationIntent, LocationResolutionStatus, TripState
from app.services.location_resolution_service import LocationMapService, resolve_location_intent
from app.services.map_errors import MapServiceError


LocationField = Literal[
    "origin", "destination", "return_destination", "outbound_departure_station",
    "outbound_arrival_station", "accommodation", "places",
]


class CityMapService(Protocol):
    def resolve_city(self, query: str) -> ResolvedCity | None: ...


@dataclass(frozen=True)
class LocationResolutionFailure:
    """A non-destructive map failure for one user-supplied location."""

    field: LocationField
    query: str
    error_code: str
    place_index: int | None = None


@dataclass(frozen=True)
class TripStateLocationResolutionResult:
    """The resolved state plus any locations that could not be queried."""

    state: TripState
    failures: list[LocationResolutionFailure]


class TripStateLocationResolutionService:
    """Resolve each unresolved TripState location without mutating the input state."""

    def __init__(
        self,
        map_service: LocationMapService,
        *,
        city_service: CityMapService | None = None,
        auto_select: bool = False,
    ) -> None:
        self._map_service = map_service
        self._city_service = city_service
        self._auto_select = auto_select

    def resolve(self, state: TripState) -> TripStateLocationResolutionResult:
        """Return a new state with Amap facts where available for each location."""
        failures: list[LocationResolutionFailure] = []
        destination = self._resolve_location(
            state.destination,
            field="destination",
            failures=failures,
        )
        region = None
        city_name = None
        if destination is not None:
            if destination.resolved_city is not None:
                region = destination.resolved_city.city_code
                city_name = destination.resolved_city.name
            elif destination.resolved_location is not None:
                region = destination.resolved_location.city_code
        origin = self._resolve_location(state.origin, field="origin", failures=failures)
        return_destination = self._resolve_location(
            state.return_destination,
            field="return_destination",
            failures=failures,
        )
        outbound_departure_station = self._resolve_station(
            state.outbound_departure_station,
            field="outbound_departure_station",
            city=origin.resolved_city if origin is not None else None,
            mode=state.intercity_travel_mode,
            failures=failures,
        )
        outbound_arrival_station = self._resolve_station(
            state.outbound_arrival_station,
            field="outbound_arrival_station",
            city=destination.resolved_city if destination is not None else None,
            mode=state.intercity_travel_mode,
            failures=failures,
        )
        accommodation = self._resolve_location(
            state.accommodation,
            field="accommodation",
            failures=failures,
            region=region, city_name=city_name,
        )
        places = [
            self._resolve_location(
                location,
                field="places",
                place_index=index,
                failures=failures,
                region=region, city_name=city_name,
            )
            for index, location in enumerate(state.places)
        ]
        return TripStateLocationResolutionResult(
            state=state.model_copy(
                update={
                    "origin": origin,
                    "destination": destination,
                    "return_destination": return_destination,
                    "outbound_departure_station": outbound_departure_station,
                    "outbound_arrival_station": outbound_arrival_station,
                    "accommodation": accommodation,
                    "places": places,
                }
            ),
            failures=failures,
        )

    def _resolve_location(
        self,
        location: LocationIntent | None,
        *,
        field: LocationField,
        failures: list[LocationResolutionFailure],
        place_index: int | None = None,
        region: str | None = None,
        city_name: str | None = None,
    ) -> LocationIntent | None:
        if location is None or location.resolution_status is LocationResolutionStatus.RESOLVED:
            return location
        if location.resolution_status is LocationResolutionStatus.AMBIGUOUS and not self._auto_select:
            return location
        try:
            if self._city_service is not None and field in {"origin", "destination", "return_destination"}:
                city = self._city_service.resolve_city(location.query)
                if city is not None:
                    return LocationIntent(query=location.query, resolution_status="resolved", resolved_city=city)
            return resolve_location_intent(
                LocationIntent(query=location.query), self._map_service,
                region=region, city_name=city_name, field=field, auto_select=self._auto_select,
            )
        except MapServiceError as error:
            failures.append(
                LocationResolutionFailure(
                    field=field,
                    query=location.query,
                    error_code=error.code,
                    place_index=place_index,
                )
            )
            return location

    def _resolve_station(
        self,
        station: LocationIntent | None,
        *,
        field: Literal["outbound_departure_station", "outbound_arrival_station"],
        city: ResolvedCity | None,
        mode: IntercityTravelMode | None,
        failures: list[LocationResolutionFailure],
    ) -> LocationIntent | None:
        """Offer only transport-mode-compatible stations for a known city."""
        station_keywords = {
            IntercityTravelMode.HIGH_SPEED_RAIL: "高铁站",
            IntercityTravelMode.TRAIN: "火车站",
            IntercityTravelMode.COACH: "汽车站",
        }
        keyword = station_keywords.get(mode)
        if keyword is None or city is None:
            return None if station is None or station.resolution_status is not LocationResolutionStatus.RESOLVED else station
        if station is not None and station.resolution_status is LocationResolutionStatus.RESOLVED:
            return station
        query = f"{city.name.removesuffix('市')}{keyword}"
        try:
            candidates = self._map_service.search_pois(query, region=city.city_code)
            candidates = list({candidate.poi_id: candidate for candidate in candidates}.values())
            candidates = [
                candidate for candidate in candidates
                if candidate.city_code in (None, city.city_code)
                and (candidate.category_code or "").startswith("150")
            ]
            if not candidates:
                return LocationIntent(query=query)
            if len(candidates) == 1:
                resolved = self._map_service.resolve_location(candidates[0].poi_id)
                return LocationIntent(
                    query=query,
                    resolution_status=LocationResolutionStatus.RESOLVED,
                    resolved_location=resolved,
                )
            return LocationIntent(
                query=query,
                resolution_status=LocationResolutionStatus.AMBIGUOUS,
                candidates=candidates,
            )
        except MapServiceError as error:
            failures.append(LocationResolutionFailure(field=field, query=query, error_code=error.code))
            return LocationIntent(query=query)
