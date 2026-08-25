import json

import httpx
import pytest
from pydantic import SecretStr

from app.services.amap_client import AmapWebApiClient
from app.services.map_errors import (
    MapConfigurationError,
    MapQuotaExceededError,
    MapTimeoutError,
    MapUpstreamError,
)


def make_client(handler) -> AmapWebApiClient:
    return AmapWebApiClient(
        SecretStr("test-amap-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_get_json_injects_key_and_prevents_parameter_override() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://restapi.amap.com/v5/place/text?keywords=%E5%A4%A9%E5%AE%89%E9%97%A8&key=test-amap-key"
        )
        return httpx.Response(200, json={"status": "1"})

    payload = make_client(handler).get_json(
        "/v5/place/text", params={"keywords": "天安门", "key": "caller-value"}
    )

    assert payload == {"status": "1"}


@pytest.mark.parametrize("api_key", [None, SecretStr("   ")])
def test_get_json_requires_a_configured_key(api_key: SecretStr | None) -> None:
    client = AmapWebApiClient(api_key)

    with pytest.raises(MapConfigurationError):
        client.get_json("v5/place/text")


def test_get_json_converts_timeouts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(MapTimeoutError):
        make_client(handler).get_json("v5/place/text")


def test_get_json_converts_rate_limits() -> None:
    client = make_client(lambda request: httpx.Response(429))

    with pytest.raises(MapQuotaExceededError):
        client.get_json("v5/place/text")


def test_get_json_converts_unsuccessful_http_responses() -> None:
    client = make_client(lambda request: httpx.Response(500))

    with pytest.raises(MapUpstreamError):
        client.get_json("v5/place/text")


def test_get_json_converts_invalid_json() -> None:
    client = make_client(
        lambda request: httpx.Response(
            200,
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
    )

    with pytest.raises(MapUpstreamError):
        client.get_json("v5/place/text")


def test_get_json_rejects_json_arrays() -> None:
    client = make_client(
        lambda request: httpx.Response(
            200,
            content=json.dumps(["not", "an", "object"]),
            headers={"content-type": "application/json"},
        )
    )

    with pytest.raises(MapUpstreamError):
        client.get_json("v5/place/text")
