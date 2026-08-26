import json

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from app.core.config import Settings
from app.services.httpx_openai_compatible_llm_provider import (
    HttpxOpenAiCompatibleLlmProvider,
    _parse_structured_content,
    _strict_json_schema,
)
from app.services.llm_provider import (
    LlmConfigurationError,
    LlmMessage,
    LlmMessageRole,
    LlmResponseError,
    LlmUpstreamError,
)
from app.services.llm_provider_factory import create_llm_provider
from app.services.llm_provider import MockLlmProvider


class ExtractedDestination(BaseModel):
    destination: str


def test_real_provider_posts_compatible_structured_request() -> None:
    captured: dict[str, object] = {}

    def fake_http_post(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"destination": "北京"})}}]},
        )

    provider = HttpxOpenAiCompatibleLlmProvider(
        api_key=SecretStr("test-key"),
        base_url=" https://models.example.test/v1/ ",
        model=" test-model ",
        http_post=fake_http_post,
    )

    result = provider.generate_structured(
        [LlmMessage(role=LlmMessageRole.USER, content="我想去北京")],
        ExtractedDestination,
    )

    assert result == ExtractedDestination(destination="北京")
    assert captured["url"] == "https://models.example.test/v1/chat/completions"
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert captured["timeout"] == 30.0
    assert captured["json"] == {
        "model": "test-model",
        "temperature": 0,
        "messages": [{"role": "user", "content": "我想去北京"}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "ExtractedDestination",
                "strict": True,
                "schema": _strict_json_schema(ExtractedDestination),
            },
        },
    }


def test_strict_schema_forbids_extra_properties_in_nested_models() -> None:
    class NestedOutput(BaseModel):
        destination: ExtractedDestination

    schema = _strict_json_schema(NestedOutput)

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["destination"]
    assert schema["$defs"]["ExtractedDestination"]["additionalProperties"] is False
    assert schema["$defs"]["ExtractedDestination"]["required"] == ["destination"]


def test_strict_schema_removes_pydantic_defaults() -> None:
    class OptionalOutput(BaseModel):
        destination: str | None = None

    schema = _strict_json_schema(OptionalOutput)

    assert "default" not in schema["properties"]["destination"]


def test_parse_structured_content_tolerates_leading_reasoning_text() -> None:
    assert _parse_structured_content("<think>reasoning</think>\n{\"destination\": \"北京\"}") == {
        "destination": "北京"
    }


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}),
    ],
)
def test_provider_maps_invalid_response_to_controlled_error(response: httpx.Response) -> None:
    provider = HttpxOpenAiCompatibleLlmProvider(
        api_key=SecretStr("test-key"),
        base_url="https://models.example.test/v1",
        model="test-model",
        http_post=lambda url, **kwargs: response,
    )

    with pytest.raises(LlmResponseError):
        provider.generate_structured([], ExtractedDestination)


@pytest.mark.parametrize(
    "error, message",
    [
        (httpx.ConnectError("unavailable"), "request failed"),
        (httpx.ReadTimeout("timed out"), "timed out"),
    ],
)
def test_provider_maps_network_errors_to_controlled_error(
    error: httpx.RequestError,
    message: str,
) -> None:
    provider = HttpxOpenAiCompatibleLlmProvider(
        api_key=SecretStr("test-key"),
        base_url="https://models.example.test/v1",
        model="test-model",
        http_post=lambda url, **kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(LlmUpstreamError, match=message):
        provider.generate_structured([], ExtractedDestination)


def test_provider_maps_http_error_to_controlled_error() -> None:
    provider = HttpxOpenAiCompatibleLlmProvider(
        api_key=SecretStr("test-key"),
        base_url="https://models.example.test/v1",
        model="test-model",
        http_post=lambda url, **kwargs: httpx.Response(401),
    )

    with pytest.raises(LlmUpstreamError, match="HTTP 401"):
        provider.generate_structured([], ExtractedDestination)


def test_factory_uses_mock_by_default_and_real_when_selected() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:password@localhost:5432/travel_agent",
        test_database_url="postgresql+psycopg://user:password@localhost:5433/travel_agent_test",
    )

    assert isinstance(create_llm_provider(settings), MockLlmProvider)

    real_settings = settings.model_copy(
        update={
            "llm_provider": "real",
            "llm_api_key": SecretStr("test-key"),
            "llm_model": "test-model",
        }
    )
    assert isinstance(
        create_llm_provider(
            real_settings,
            http_post=lambda url, **kwargs: httpx.Response(200),
        ),
        HttpxOpenAiCompatibleLlmProvider,
    )


def test_real_factory_requires_key_and_model() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:password@localhost:5432/travel_agent",
        test_database_url="postgresql+psycopg://user:password@localhost:5433/travel_agent_test",
        llm_provider="real",
    )

    with pytest.raises(LlmConfigurationError, match="LLM_API_KEY"):
        create_llm_provider(settings)
