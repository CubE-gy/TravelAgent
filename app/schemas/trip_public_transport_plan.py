"""Stage 3 contracts for a user-specified public-transport Trip plan."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import IntercityTravelMode
from app.schemas.map import ResolvedLocation, Route


class TripRouteNodeKind(str, Enum):
    """A role played by one confirmed location in a door-to-door route."""

    ORIGIN = "origin"
    OUTBOUND_DEPARTURE_NODE = "outbound_departure_node"
    OUTBOUND_ARRIVAL_NODE = "outbound_arrival_node"
    ACCOMMODATION = "accommodation"
    PLACE = "place"
    RETURN_DEPARTURE_NODE = "return_departure_node"
    RETURN_ARRIVAL_NODE = "return_arrival_node"
    RETURN_DESTINATION = "return_destination"


class TripRouteLegKind(str, Enum):
    """A required movement between two adjacent route-skeleton nodes."""

    TO_OUTBOUND_DEPARTURE_NODE = "to_outbound_departure_node"
    OUTBOUND_INTERCITY = "outbound_intercity"
    FROM_OUTBOUND_ARRIVAL_NODE = "from_outbound_arrival_node"
    DAY_START = "day_start"
    DAY_BETWEEN_PLACES = "day_between_places"
    DAY_RETURN = "day_return"
    TO_RETURN_DEPARTURE_NODE = "to_return_departure_node"
    RETURN_INTERCITY = "return_intercity"
    FROM_RETURN_ARRIVAL_NODE = "from_return_arrival_node"


class IntercityTransportFactSource(str, Enum):
    """The provenance of a confirmed intercity transport record."""

    USER_CONFIRMED = "user_confirmed"


class TripRouteFactSource(str, Enum):
    """The authoritative source of a complete Trip-plan leg."""

    AMAP_LOCAL_PUBLIC_TRANSPORT = "amap_local_public_transport"
    USER_CONFIRMED_INTERCITY = "user_confirmed_intercity"


class DailyPlacePlan(BaseModel):
    """A user-specified, ordered set of existing TripState places for one day."""

    day_number: int = Field(ge=1)
    place_poi_ids: list[str] = Field(min_length=1)

    @field_validator("place_poi_ids")
    @classmethod
    def place_poi_ids_must_be_non_blank_and_unique(cls, value: list[str]) -> list[str]:
        normalized_ids = [poi_id.strip() for poi_id in value]
        if any(not poi_id for poi_id in normalized_ids):
            raise ValueError("place_poi_ids must not contain blank values")
        if len(normalized_ids) != len(set(normalized_ids)):
            raise ValueError("place_poi_ids must not contain duplicates within one day")
        return normalized_ids


class IntercityPublicTransportLeg(BaseModel):
    """One user-confirmed intercity movement and its two transport nodes."""

    travel_mode: IntercityTravelMode
    departure_poi_id: str = Field(min_length=1, max_length=200)
    arrival_poi_id: str = Field(min_length=1, max_length=200)
    fact: "UserConfirmedIntercityTransportFact"

    @field_validator("travel_mode")
    @classmethod
    def travel_mode_must_be_public_transport(cls, value: IntercityTravelMode) -> IntercityTravelMode:
        if value is IntercityTravelMode.DRIVING:
            raise ValueError("intercity public transport leg must not use driving")
        return value

    @model_validator(mode="after")
    def nodes_must_be_distinct(self) -> "IntercityPublicTransportLeg":
        if self.departure_poi_id == self.arrival_poi_id:
            raise ValueError("intercity departure and arrival nodes must be distinct")
        return self


class ResolvedIntercityPublicTransportLeg(BaseModel):
    """An intercity leg whose POI IDs have been confirmed by the Stage 1 map service."""

    travel_mode: IntercityTravelMode
    departure_node: ResolvedLocation
    arrival_node: ResolvedLocation
    fact: "UserConfirmedIntercityTransportFact"


class UserConfirmedIntercityTransportFact(BaseModel):
    """A non-live intercity record supplied and confirmed by the user."""

    source: IntercityTransportFactSource = IntercityTransportFactSource.USER_CONFIRMED
    service_identifier: str = Field(min_length=1, max_length=100)
    duration_seconds: int = Field(gt=0)
    distance_meters: int | None = Field(default=None, ge=0)
    departure_time: datetime | None = None
    arrival_time: datetime | None = None

    @field_validator("service_identifier")
    @classmethod
    def service_identifier_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("service_identifier must not be blank")
        return normalized_value

    @model_validator(mode="after")
    def times_must_be_complete_and_ordered(self) -> "UserConfirmedIntercityTransportFact":
        if (self.departure_time is None) != (self.arrival_time is None):
            raise ValueError("departure_time and arrival_time must be provided together")
        if (
            self.departure_time is not None
            and self.arrival_time is not None
            and self.arrival_time <= self.departure_time
        ):
            raise ValueError("arrival_time must be after departure_time")
        return self


class PublicTransportPlanningRequest(BaseModel):
    """Extra confirmed planning choices that complement, but do not duplicate, TripState."""

    trip_id: UUID
    outbound_intercity: IntercityPublicTransportLeg
    return_intercity: IntercityPublicTransportLeg
    daily_places: list[DailyPlacePlan] = Field(min_length=1)

    @model_validator(mode="after")
    def daily_place_days_must_be_unique(self) -> "PublicTransportPlanningRequest":
        day_numbers = [daily_plan.day_number for daily_plan in self.daily_places]
        if len(day_numbers) != len(set(day_numbers)):
            raise ValueError("daily_places must not contain duplicate day_number values")
        return self


class ResolvedPublicTransportPlanningRequest(BaseModel):
    """Internal planning input containing Stage 1-confirmed intercity endpoints."""

    trip_id: UUID
    outbound_intercity: ResolvedIntercityPublicTransportLeg
    return_intercity: ResolvedIntercityPublicTransportLeg
    daily_places: list[DailyPlacePlan]


class TripRouteNode(BaseModel):
    """One resolved point in an assembled door-to-door route skeleton."""

    kind: TripRouteNodeKind
    location: ResolvedLocation
    day_number: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def day_number_must_match_node_kind(self) -> "TripRouteNode":
        if self.kind is TripRouteNodeKind.PLACE and self.day_number is None:
            raise ValueError("place route nodes require day_number")
        if self.kind is not TripRouteNodeKind.PLACE and self.day_number is not None:
            raise ValueError("only place route nodes may contain day_number")
        return self


class TripRouteSkeletonLeg(BaseModel):
    """One planned movement awaiting a later Stage 3 map-fact query."""

    kind: TripRouteLegKind
    origin_node_index: int = Field(ge=0)
    destination_node_index: int = Field(ge=0)

    @model_validator(mode="after")
    def leg_nodes_must_be_distinct(self) -> "TripRouteSkeletonLeg":
        if self.origin_node_index == self.destination_node_index:
            raise ValueError("route skeleton leg endpoints must be distinct")
        return self


class TripRouteSkeleton(BaseModel):
    """Ordered nodes and movements for a complete public-transport Trip route."""

    trip_id: UUID
    nodes: list[TripRouteNode] = Field(min_length=2)
    legs: list[TripRouteSkeletonLeg] = Field(min_length=1)

    @model_validator(mode="after")
    def legs_must_reference_existing_nodes(self) -> "TripRouteSkeleton":
        last_node_index = len(self.nodes) - 1
        for leg in self.legs:
            if (
                leg.origin_node_index > last_node_index
                or leg.destination_node_index > last_node_index
            ):
                raise ValueError("route skeleton leg must reference an existing node")
        return self


class LocalPublicTransportRouteFact(BaseModel):
    """A real Amap route bound to one non-intercity route-skeleton leg."""

    trip_id: UUID
    skeleton_leg: TripRouteSkeletonLeg
    route: Route


class PublicTransportTripPlanLeg(BaseModel):
    """One complete Trip-plan leg with an explicit, non-interchangeable fact source."""

    kind: TripRouteLegKind
    origin: ResolvedLocation
    destination: ResolvedLocation
    fact_source: TripRouteFactSource
    local_route: Route | None = None
    intercity_fact: UserConfirmedIntercityTransportFact | None = None

    @model_validator(mode="after")
    def route_fact_must_match_leg_kind(self) -> "PublicTransportTripPlanLeg":
        is_intercity = self.kind in {
            TripRouteLegKind.OUTBOUND_INTERCITY,
            TripRouteLegKind.RETURN_INTERCITY,
        }
        if is_intercity:
            if (
                self.fact_source is not TripRouteFactSource.USER_CONFIRMED_INTERCITY
                or self.intercity_fact is None
                or self.local_route is not None
            ):
                raise ValueError("intercity legs require only a user-confirmed intercity fact")
        elif (
            self.fact_source is not TripRouteFactSource.AMAP_LOCAL_PUBLIC_TRANSPORT
            or self.local_route is None
            or self.intercity_fact is not None
        ):
            raise ValueError("local legs require only an Amap local public-transport route")
        return self


class PublicTransportTripPlan(BaseModel):
    """A complete door-to-door public-transport plan in the original skeleton order."""

    trip_id: UUID
    nodes: list[TripRouteNode] = Field(min_length=2)
    legs: list[PublicTransportTripPlanLeg] = Field(min_length=1)
