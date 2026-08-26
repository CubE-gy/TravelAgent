"""Provider-neutral contract for structured LLM calls."""

from enum import Enum
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, Field, ValidationError, field_validator


class LlmMessageRole(str, Enum):
    """The supported roles in a model conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LlmMessage(BaseModel):
    """One normalized message supplied to an LLM Provider."""

    role: LlmMessageRole
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("content must not be blank")
        return normalized_value


StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


class LlmProviderError(Exception):
    """Base error for controlled failures during an LLM Provider call."""


class LlmConfigurationError(LlmProviderError):
    """Raised when an LLM Provider has incomplete local configuration."""


class LlmResponseError(LlmProviderError):
    """Raised when a Provider response cannot satisfy the requested schema."""


class LlmUpstreamError(LlmProviderError):
    """Raised when a Provider request fails outside the application's control."""


@runtime_checkable
class LlmProvider(Protocol):
    """A replaceable provider that returns a validated structured response."""

    def generate_structured(
        self,
        messages: list[LlmMessage],
        response_model: type[StructuredOutput],
    ) -> StructuredOutput: ...


class MockLlmProvider:
    """A non-network Provider that returns explicitly supplied test data."""

    def __init__(self, response_data: dict[str, Any] | None = None) -> None:
        self.response_data = response_data
        self.calls: list[tuple[list[LlmMessage], type[BaseModel]]] = []

    def generate_structured(
        self,
        messages: list[LlmMessage],
        response_model: type[StructuredOutput],
    ) -> StructuredOutput:
        self.calls.append((messages, response_model))
        if self.response_data is None:
            raise LlmResponseError("mock LLM response data is not configured")
        try:
            return response_model.model_validate(self.response_data)
        except ValidationError as error:
            raise LlmResponseError("mock LLM response does not match the requested schema") from error
