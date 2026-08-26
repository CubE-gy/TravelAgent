from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TripCreate(BaseModel):
    """Validated input required to create a travel plan."""

    name: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("name must not be blank")
        return normalized_value

    @model_validator(mode="after")
    def start_date_must_not_follow_end_date(self) -> "TripCreate":
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class TripRead(BaseModel):
    """A persisted travel plan returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None
    start_date: date | None
    end_date: date | None
    created_at: datetime
    updated_at: datetime


class TripUpdate(BaseModel):
    """Fields that may be changed on an existing travel plan."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("name")
    @classmethod
    def updated_name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("name must not be blank")
        return normalized_value

    @model_validator(mode="after")
    def update_must_contain_at_least_one_field(self) -> "TripUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        null_fields = [
            field_name
            for field_name in self.model_fields_set
            if getattr(self, field_name) is None
        ]
        if null_fields:
            raise ValueError(f"{', '.join(sorted(null_fields))} must not be null")
        return self
