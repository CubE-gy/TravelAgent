"""ValidationRetryingLlmProvider turns a schema rejection into one self-correction retry."""

from pydantic import BaseModel, Field

from app.services.llm_provider import (
    LlmMessage,
    LlmMessageRole,
    LlmProvider,
    LlmResponseError,
)
from app.services.validation_retrying_llm_provider import ValidationRetryingLlmProvider


class _Schema(BaseModel):
    value: str = Field(min_length=1)


class _ScriptedProvider:
    def __init__(self, outputs: list[dict | None]) -> None:
        self._outputs: list[dict | None] = list(outputs)
        self.calls: list[list[LlmMessage]] = []

    def generate_structured(self, messages, response_model):
        self.calls.append(list(messages))
        output = self._outputs.pop(0)
        if output is None:
            raise LlmResponseError("schema rejected")
        return response_model.model_validate(output)


def test_no_retry_on_first_success() -> None:
    inner = _ScriptedProvider([{"value": "ok"}])
    wrapper = ValidationRetryingLlmProvider(inner)

    result = wrapper.generate_structured(
        [LlmMessage(role=LlmMessageRole.USER, content="go")], _Schema
    )

    assert result.value == "ok"
    assert len(inner.calls) == 1


def test_one_retry_on_first_failure_then_succeeds() -> None:
    inner = _ScriptedProvider([None, {"value": "fixed"}])
    wrapper = ValidationRetryingLlmProvider(inner)

    result = wrapper.generate_structured(
        [LlmMessage(role=LlmMessageRole.USER, content="go")], _Schema
    )

    assert result.value == "fixed"
    assert len(inner.calls) == 2
    assert "rejected" in inner.calls[1][-1].content
    assert inner.calls[1][-1].role is LlmMessageRole.SYSTEM


def test_second_failure_is_propagated() -> None:
    inner = _ScriptedProvider([None, None])
    wrapper = ValidationRetryingLlmProvider(inner)

    with __import__("pytest").raises(LlmResponseError):
        wrapper.generate_structured(
            [LlmMessage(role=LlmMessageRole.USER, content="go")], _Schema
        )
    assert len(inner.calls) == 2
