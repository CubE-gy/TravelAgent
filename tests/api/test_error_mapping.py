"""Contract tests for map dependency error mapping."""

import pytest

from app.api.error_mapping import map_map_service_error
from app.services.map_errors import (
    MapConfigurationError,
    MapNoResultsError,
    MapQuotaExceededError,
    MapServiceError,
    MapTimeoutError,
    MapUpstreamError,
)


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (MapNoResultsError(), 422),
        (MapTimeoutError(), 504),
        (MapConfigurationError(), 503),
        (MapQuotaExceededError(), 503),
        (MapUpstreamError(), 502),
        (MapServiceError(), 502),
    ],
)
def test_map_errors_have_one_stable_http_status(error: MapServiceError, expected_status: int) -> None:
    response = map_map_service_error(
        error,
        no_results_detail="no results",
        unavailable_detail="unavailable",
        timeout_detail="timed out",
        upstream_detail="upstream failed",
    )

    assert response.status_code == expected_status
