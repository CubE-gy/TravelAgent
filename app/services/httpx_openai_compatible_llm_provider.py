"""httpx implementation for OpenAI-compatible structured model calls."""

import json
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from app.core.config import Settings
from app.services.llm_provider import (
    LlmConfigurationError,
    LlmMessage,
    LlmResponseError,
    LlmUpstreamError,
    StructuredOutput,
)


HttpPost = Callable[..., httpx.Response]


def _strict_json_schema(response_model: type[StructuredOutput]) -> dict[str, Any]:
    """Return an OpenAI-compatible strict schema for all nested object models."""
    schema = response_model.model_json_schema()
    _forbid_additional_properties(schema)
    return schema


def _forbid_additional_properties(value: Any) -> None:
    """Set the strict-schema requirement recursively without changing Pydantic parsing."""
    if isinstance(value, dict):
        value.pop("default", None)
        if value.get("type") == "object" or "properties" in value:
            value["additionalProperties"] = False
            value["required"] = list(value.get("properties", {}))
        for nested_value in value.values():
            _forbid_additional_properties(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            _forbid_additional_properties(nested_value)


def _parse_structured_content(content: str) -> Any:
    """Parse JSON, tolerating unsupported reasoning text before the JSON object."""
    try:
        return json.loads(content)
    except json.JSONDecodeError as initial_error:
        object_start = content.find("{")
        if object_start < 0:
            raise initial_error
        try:
            parsed, _ = json.JSONDecoder().raw_decode(content[object_start:])
        except json.JSONDecodeError:
            raise initial_error
        return parsed


def default_http_post(
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, Any],
    timeout: float,
) -> httpx.Response:
    """Make the synchronous request used by the real compatible Provider."""
    return httpx.post(url, headers=headers, json=json, timeout=timeout)


class HttpxOpenAiCompatibleLlmProvider:
    """Call an OpenAI-compatible chat-completions endpoint through httpx."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        model: str,
        http_post: HttpPost = default_http_post,
    ) -> None:
        normalized_api_key = api_key.get_secret_value().strip()
        normalized_base_url = base_url.strip().rstrip("/")
        normalized_model = model.strip()
        if not normalized_api_key:
            raise LlmConfigurationError("LLM_API_KEY must not be blank")
        if not normalized_base_url:
            raise LlmConfigurationError("LLM_BASE_URL must not be blank")
        if not normalized_model:
            raise LlmConfigurationError("LLM_MODEL must not be blank")

        self._api_key = normalized_api_key
        self._base_url = normalized_base_url
        self._model = normalized_model
        self._http_post = http_post

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        http_post: HttpPost = default_http_post,
    ) -> "HttpxOpenAiCompatibleLlmProvider":
        """Build the real compatible Provider from environment-backed settings."""
        if settings.llm_api_key is None:
            raise LlmConfigurationError("LLM_API_KEY is required")
        if settings.llm_model is None:
            raise LlmConfigurationError("LLM_MODEL is required")
        return cls(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            http_post=http_post,
        )

    def generate_structured(
        self,
        messages: list[LlmMessage],
        response_model: type[StructuredOutput],
    ) -> StructuredOutput:
        """Request a JSON-schema response and validate it as the target model."""
        try:
            response = self._http_post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "temperature": 0,
                    "messages": [
                        {"role": message.role.value, "content": message.content}
                        for message in messages
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": response_model.__name__,
                            "strict": True,
                            "schema": _strict_json_schema(response_model),
                        },
                    },
                },
                timeout=30.0,
            )
        except httpx.ReadTimeout as error:
            raise LlmUpstreamError("LLM Provider request timed out") from error
        except httpx.RequestError as error:
            raise LlmUpstreamError("LLM Provider request failed") from error

        if response.status_code >= 400:
            raise LlmUpstreamError(f"LLM Provider returned HTTP {response.status_code}")

        try:
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("LLM response content must be a string")
            return response_model.model_validate(_parse_structured_content(content))
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as error:
            raise LlmResponseError("LLM Provider returned an invalid structured response") from error
