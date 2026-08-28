"""Translate controlled dependency failures into stable HTTP responses."""

from fastapi import HTTPException, status

from app.services.map_errors import (
    MapConfigurationError,
    MapNoResultsError,
    MapQuotaExceededError,
    MapServiceError,
    MapTimeoutError,
)


def map_map_service_error(
    error: MapServiceError,
    *,
    no_results_detail: str,
    unavailable_detail: str,
    timeout_detail: str,
    upstream_detail: str,
) -> HTTPException:
    """Return the standardized HTTP response for one map dependency failure."""
    if isinstance(error, MapNoResultsError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=no_results_detail,
        )
    if isinstance(error, MapTimeoutError):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=timeout_detail,
        )
    if isinstance(error, (MapConfigurationError, MapQuotaExceededError)):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=unavailable_detail,
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=upstream_detail,
    )
