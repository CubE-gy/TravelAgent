from enum import Enum


class TravelMode(str, Enum):
    """Travel modes currently supported by TravelAgent V1."""

    PUBLIC_TRANSPORT = "public_transport"
    DRIVING = "driving"


class VehicleEnergyType(str, Enum):
    """Vehicle energy types currently supported by TravelAgent V1."""

    GASOLINE = "gasoline"
    ELECTRIC = "electric"


class RouteSegmentMode(str, Enum):
    """Concrete travel modes that may occur inside a route."""

    DRIVING = "driving"
    WALKING = "walking"
    BUS = "bus"
    SUBWAY = "subway"
    RAILWAY = "railway"
