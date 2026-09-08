from pydantic import BaseModel

import pytest

from app.services.llm_call_tracer import TracingLlmProvider
from app.services.llm_provider import (
    LlmMessage,
    LlmMessageRole,
    LlmResponseError,
    MockLlmProvider,
)


class SampleDecision(BaseModel):
    value: str


def _messages() -> list[LlmMessage]:
    return [LlmMessage(role=LlmMessageRole.USER, content="我要去北京")]


def test_successful_call_is_recorded_with_its_response_model() -> None:
    tracer = TracingLlmProvider(MockLlmProvider({"value": "ok"}))

    assert tracer.generate_structured(_messages(), SampleDecision).value == "ok"

    assert len(tracer.records) == 1
    assert tracer.records[0].response_model == "SampleDecision"
    assert tracer.records[0].error is None
    assert tracer.records[0].latency_ms >= 0


def test_failed_call_is_recorded_and_reraised() -> None:
    tracer = TracingLlmProvider(MockLlmProvider(None))

    with pytest.raises(LlmResponseError):
        tracer.generate_structured(_messages(), SampleDecision)

    assert len(tracer.records) == 1
    assert tracer.records[0].response_model == "SampleDecision"
    assert tracer.records[0].error == "LlmResponseError"


def test_records_keep_call_order_and_accumulate() -> None:
    tracer = TracingLlmProvider(MockLlmProvider({"value": "ok"}))

    tracer.generate_structured(_messages(), SampleDecision)
    tracer.generate_structured(_messages(), SampleDecision)

    assert [record.response_model for record in tracer.records] == [
        "SampleDecision",
        "SampleDecision",
    ]
    assert all(record.error is None for record in tracer.records)


def test_records_are_isolated_between_tracers() -> None:
    first = TracingLlmProvider(MockLlmProvider({"value": "ok"}))
    second = TracingLlmProvider(MockLlmProvider({"value": "ok"}))

    first.generate_structured(_messages(), SampleDecision)

    assert len(first.records) == 1
    assert second.records == ()
