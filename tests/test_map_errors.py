import pytest

from app.services.map_errors import (
    MapConfigurationError,
    MapNoResultsError,
    MapQuotaExceededError,
    MapServiceError,
    MapTimeoutError,
    MapUpstreamError,
)


@pytest.mark.parametrize(
    ("error_type", "code", "message"),
    [
        (
            MapConfigurationError,
            "map_configuration_error",
            "The map service is not configured.",
        ),
        (MapTimeoutError, "map_timeout", "The map service request timed out."),
        (
            MapQuotaExceededError,
            "map_quota_exceeded",
            "The map service request exceeded its allowed quota.",
        ),
        (
            MapUpstreamError,
            "map_upstream_error",
            "The map service returned an unexpected response.",
        ),
        (
            MapNoResultsError,
            "map_no_results",
            "The map service found no matching results.",
        ),
    ],
)
def test_map_errors_have_stable_safe_public_details(
    error_type: type[MapServiceError], code: str, message: str
) -> None:
    error = error_type()

    assert isinstance(error, MapServiceError)
    assert error.code == code
    assert str(error) == message


def test_base_map_error_has_a_stable_safe_public_detail() -> None:
    error = MapServiceError()

    assert error.code == "map_service_error"
    assert str(error) == "The map service could not complete the request."
