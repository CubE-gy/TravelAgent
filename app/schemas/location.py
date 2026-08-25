from pydantic import BaseModel, Field, field_validator, model_validator


class Location(BaseModel):
    """A user-supplied place before map facts are introduced."""

    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("name must not be blank")
        return normalized_value

    @field_validator("address")
    @classmethod
    def normalize_address(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return value.strip() or None

    @model_validator(mode="after")
    def coordinates_must_be_provided_together(self) -> "Location":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self
