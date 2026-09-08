"""Let a failing structured response self-correct with one bounded retry.

The Provider layer wraps validation errors as ``LlmResponseError``. We catch
that error once, append a system note describing the rejection, and let the
model try again. After the second failure the original error is re-raised so
the caller still sees a deterministic failure.
"""

from typing import Any

from app.services.llm_provider import (
    LlmMessage,
    LlmMessageRole,
    LlmProvider,
    LlmResponseError,
    StructuredOutput,
)


class ValidationRetryingLlmProvider:
    """Wrap a Provider so one structured-output rejection is not a hard 500."""

    def __init__(self, inner: LlmProvider) -> None:
        self._inner = inner

    @property
    def inner(self) -> LlmProvider:
        return self._inner

    def generate_structured(
        self,
        messages: list[LlmMessage],
        response_model: type[StructuredOutput],
    ) -> StructuredOutput:
        try:
            return self._inner.generate_structured(messages, response_model)
        except LlmResponseError as first_error:
            retry_messages = list(messages) + [
                LlmMessage(
                    role=LlmMessageRole.SYSTEM,
                    content=(
                        "Your previous structured response was rejected: "
                        + str(first_error)
                        + " Return a single corrected object that satisfies the schema."
                    ),
                )
            ]
            return self._inner.generate_structured(retry_messages, response_model)


__all__ = ["ValidationRetryingLlmProvider"]
