from collections.abc import Mapping
from typing import Any, ClassVar

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
    quota_infocodes: ClassVar[frozenset[str]] = frozenset(
        {
            "10003",  # DAILY_QUERY_OVER_LIMIT
            "10004",  # ACCESS_TOO_FREQUENT
            "10010",  # IP_QUERY_OVER_LIMIT
            "10014",  # QPS_HAS_EXCEEDED_THE_LIMIT
            "10015",  # QPS limit at the gateway
            "10019",  # CQPS_HAS_EXCEEDED_THE_LIMIT
            "10020",  # CKQPS_HAS_EXCEEDED_THE_LIMIT
            "10021",  # CUQPS_HAS_EXCEEDED_THE_LIMIT
            "10029",  # ABROAD_DAILY_QUERY_OVER_LIMIT
            "10044",  # USER_DAILY_QUERY_OVER_LIMIT
            "10045",  # USER_ABROAD_DAILY_QUERY_OVER_LIMIT
        }
    )

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
        if payload.get("infocode") in self.quota_infocodes:
            raise MapQuotaExceededError()
        return payload

    def _get_api_key(self) -> str:
        if self._api_key is None:
            raise MapConfigurationError()
        api_key = self._api_key.get_secret_value().strip()
        if not api_key:
            raise MapConfigurationError()
        return api_key
