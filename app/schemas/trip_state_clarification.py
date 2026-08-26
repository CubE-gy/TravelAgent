"""Validated LLM wording for deterministic TripState clarification topics."""

from pydantic import BaseModel, Field, field_validator


class ClarificationQuestion(BaseModel):
    """One user-facing question for one Python-determined clarification topic."""

    topic_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=500)

    @field_validator("topic_id", "question")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("value must not be blank")
        return normalized_value


class TripStateClarification(BaseModel):
    """All user-facing questions required after one TripState update."""

    questions: list[ClarificationQuestion] = Field(default_factory=list)
