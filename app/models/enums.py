from enum import Enum


class TravelMode(str, Enum):
    """Travel modes currently supported by TravelAgent V1."""

    PUBLIC_TRANSPORT = "public_transport"
    DRIVING = "driving"


class VehicleEnergyType(str, Enum):
    """Vehicle energy types currently supported by TravelAgent V1."""

    GASOLINE = "gasoline"
    ELECTRIC = "electric"
