"""Record every structured provider call performed within one Agent turn."""

from time import perf_counter

from pydantic import BaseModel

from app.services.llm_provider import (
    LlmMessage,
    LlmProvider,
    StructuredOutput,
)


class LlmCallRecord(BaseModel):
    """One completed structured provider call and its outcome."""

    response_model: str
    latency_ms: int
    error: str | None = None


class TracingLlmProvider:
    """Wrap one Provider and remember each call it performs this turn."""

    def __init__(self, provider: LlmProvider) -> None:
        self._provider = provider
        self._records: list[LlmCallRecord] = []

    @property
    def records(self) -> tuple[LlmCallRecord, ...]:
        return tuple(self._records)

    def generate_structured(
        self,
        messages: list[LlmMessage],
        response_model: type[StructuredOutput],
    ) -> StructuredOutput:
        started = perf_counter()
        error: str | None = None
        try:
            return self._provider.generate_structured(messages, response_model)
        except Exception as provider_error:
            error = type(provider_error).__name__
            raise
        finally:
            self._records.append(
                LlmCallRecord(
                    response_model=response_model.__name__,
                    latency_ms=int((perf_counter() - started) * 1000),
                    error=error,
                )
            )
