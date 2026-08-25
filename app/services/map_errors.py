from typing import ClassVar


class MapServiceError(Exception):
    """Base exception for predictable failures from the map fact service."""

    code: ClassVar[str] = "map_service_error"
    message: ClassVar[str] = "The map service could not complete the request."

    def __init__(self) -> None:
        super().__init__(self.message)


class MapConfigurationError(MapServiceError):
    """Raised when map service configuration is missing or invalid."""

    code = "map_configuration_error"
    message = "The map service is not configured."


class MapTimeoutError(MapServiceError):
    """Raised when a map provider request exceeds its time limit."""

    code = "map_timeout"
    message = "The map service request timed out."


class MapQuotaExceededError(MapServiceError):
    """Raised when the map provider rejects a request for quota or rate limits."""

    code = "map_quota_exceeded"
    message = "The map service request exceeded its allowed quota."


class MapUpstreamError(MapServiceError):
    """Raised when the map provider returns an unavailable or invalid response."""

    code = "map_upstream_error"
    message = "The map service returned an unexpected response."


class MapNoResultsError(MapServiceError):
    """Raised when a successful map query has no matching facts."""

    code = "map_no_results"
    message = "The map service found no matching results."
