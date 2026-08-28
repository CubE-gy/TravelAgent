"""Shared contracts for data crossing the HTTP API boundary."""

from pydantic import BaseModel, ConfigDict


class ApiRequest(BaseModel):
    """Reject undeclared client input so misspelled fields cannot be ignored."""

    model_config = ConfigDict(extra="forbid")
