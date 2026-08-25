import pytest
from pydantic import ValidationError

from app.models.enums import VehicleEnergyType
from app.schemas.vehicle import Vehicle


@pytest.mark.parametrize(
    ("energy_type", "range_km"),
    [
        (VehicleEnergyType.GASOLINE, 650),
        (VehicleEnergyType.ELECTRIC, 480.5),
    ],
)
def test_vehicle_accepts_supported_energy_type_and_positive_range(
    energy_type: VehicleEnergyType, range_km: float
) -> None:
    vehicle = Vehicle(energy_type=energy_type, range_km=range_km)

    assert vehicle.model_dump(mode="json") == {
        "energy_type": energy_type.value,
        "range_km": range_km,
    }


@pytest.mark.parametrize("range_km", [0, -1])
def test_vehicle_rejects_non_positive_range(range_km: float) -> None:
    with pytest.raises(ValidationError):
        Vehicle(energy_type=VehicleEnergyType.ELECTRIC, range_km=range_km)
