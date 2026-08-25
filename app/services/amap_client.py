from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import SecretStr

from app.services.map_errors import (
    MapConfigurationError,
    MapQuotaExceededError,
    MapTimeoutError,
    MapUpstreamError,
)


class AmapWebApiClient:
    """Low-level, safe HTTP client for Amap Web API requests."""

    base_url = "https://restapi.amap.com"

    def __init__(
        self,
        api_key: SecretStr | None,
        *,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)

    def get_json(
        self,
        path: str,
        params: Mapping[str, str | int | float] | None = None,
    ) -> dict[str, Any]:
        """Request a JSON object while keeping provider details within this client."""
        api_key = self._get_api_key()
        request_params = {**(params or {}), "key": api_key}

        try:
            response = self._client.get(
                f"{self.base_url}/{path.lstrip('/')}",
                params=request_params,
            )
        except httpx.TimeoutException as error:
            raise MapTimeoutError() from error
        except httpx.RequestError as error:
            raise MapUpstreamError() from error

        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise MapQuotaExceededError()
        if response.is_error:
            raise MapUpstreamError()

        try:
            payload = response.json()
        except ValueError as error:
            raise MapUpstreamError() from error

        if not isinstance(payload, dict):
            raise MapUpstreamError()
        return payload

    def _get_api_key(self) -> str:
        if self._api_key is None:
            raise MapConfigurationError()
        api_key = self._api_key.get_secret_value().strip()
        if not api_key:
            raise MapConfigurationError()
        return api_key
