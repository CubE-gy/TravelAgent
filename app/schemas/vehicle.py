from pydantic import BaseModel, Field

from app.models.enums import VehicleEnergyType


class Vehicle(BaseModel):
    """Minimum vehicle data required for future driving plans."""

    energy_type: VehicleEnergyType
    range_km: float = Field(gt=0)
