"""Decision facts recorded for one conversation turn."""

from pydantic import BaseModel


class LlmCallTrace(BaseModel):
    """One structured provider call performed while handling a turn."""

    response_model: str
    latency_ms: int
    error: str | None = None


class LocationFailureTrace(BaseModel):
    """One location a previous turn could not confirm on the map."""

    field: str
    query: str
    error_code: str


class AgentTurnTrace(BaseModel):
    """How one turn was decided, kept for replay and later evaluation."""

    llm_calls: list[LlmCallTrace] = []
    decision: str | None = None
    operations: list[str] = []
    location_failures: list[LocationFailureTrace] = []
    recommendation_count: int = 0
