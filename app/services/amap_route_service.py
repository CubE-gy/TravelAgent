from typing import Any

from app.models.enums import RouteSegmentMode, TravelMode
from app.schemas.map import Polyline, ResolvedLocation, Route, RouteSegment
from app.services.amap_poi_service import JsonMapClient
from app.services.amap_polyline import parse_amap_polyline
from app.services.map_errors import MapNoResultsError, MapUpstreamError


class AmapRouteService:
    """Converts Amap V5 route responses into project route facts."""

    def __init__(self, client: JsonMapClient) -> None:
        self._client = client

    def driving(self, origin: ResolvedLocation, destination: ResolvedLocation) -> Route:
        """Retrieve one complete driving route between confirmed POIs."""
        payload = self._client.get_json(
            "v5/direction/driving",
            params={
                "origin": self._format_location(origin),
                "destination": self._format_location(destination),
                "origin_id": origin.poi_id,
                "destination_id": destination.poi_id,
                "show_fields": "cost,polyline",
            },
        )
        if payload.get("status") != "1":
            raise MapUpstreamError()

        try:
            paths = payload["route"]["paths"]
            if not isinstance(paths, list):
                raise TypeError("paths must be a list")
            if not paths:
                raise MapNoResultsError()
            return self._to_driving_route(paths[0])
        except MapNoResultsError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise MapUpstreamError() from error

    def local_public_transport(
        self, origin: ResolvedLocation, destination: ResolvedLocation
    ) -> Route:
        """Retrieve one city-local public transport route between confirmed POIs."""
        origin_city_code = self._require_city_code(origin, field_name="origin")
        destination_city_code = self._require_city_code(destination, field_name="destination")
        if origin_city_code != destination_city_code:
            raise ValueError("local public transport requires locations in the same city")

        payload = self._client.get_json(
            "v5/direction/transit/integrated",
            params={
                "origin": self._format_location(origin),
                "destination": self._format_location(destination),
                "originpoi": origin.poi_id,
                "destinationpoi": destination.poi_id,
                "city1": origin_city_code,
                "city2": destination_city_code,
                "AlternativeRoute": "1",
                "show_fields": "cost,polyline",
            },
        )
        if payload.get("status") != "1":
            raise MapUpstreamError()

        try:
            transits = payload["route"]["transits"]
            if not isinstance(transits, list):
                raise TypeError("transits must be a list")
            if not transits:
                raise MapNoResultsError()
            return self._to_local_public_transport_route(transits[0])
        except MapNoResultsError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise MapUpstreamError() from error

    @staticmethod
    def _format_location(location: ResolvedLocation) -> str:
        return f"{location.coordinate.longitude:.6f},{location.coordinate.latitude:.6f}"

    @staticmethod
    def _require_city_code(location: ResolvedLocation, *, field_name: str) -> str:
        if location.city_code is None:
            raise ValueError(f"{field_name} city_code is required")
        city_code = location.city_code.strip()
        if not city_code:
            raise ValueError(f"{field_name} city_code is required")
        return city_code

    @staticmethod
    def _to_driving_route(path: object) -> Route:
        if not isinstance(path, dict):
            raise TypeError("path must be an object")

        steps = path.get("steps")
        if not isinstance(steps, list):
            raise TypeError("steps must be a list")
        segments = [AmapRouteService._to_driving_segment(step) for step in steps]
        return Route(
            travel_mode=TravelMode.DRIVING,
            distance_meters=AmapRouteService._parse_nonnegative_int(path.get("distance")),
            duration_seconds=AmapRouteService._parse_duration(path.get("cost")),
            segments=segments,
        )

    @staticmethod
    def _to_local_public_transport_route(transit: object) -> Route:
        if not isinstance(transit, dict):
            raise TypeError("transit must be an object")
        raw_segments = transit.get("segments")
        if not isinstance(raw_segments, list):
            raise TypeError("transit segments must be a list")

        segments: list[RouteSegment] = []
        for raw_segment in raw_segments:
            segments.extend(AmapRouteService._to_local_public_transport_segments(raw_segment))

        return Route(
            travel_mode=TravelMode.PUBLIC_TRANSPORT,
            distance_meters=AmapRouteService._parse_nonnegative_int(transit.get("distance")),
            duration_seconds=AmapRouteService._parse_duration(transit.get("cost")),
            segments=segments,
        )

    @staticmethod
    def _to_local_public_transport_segments(raw_segment: object) -> list[RouteSegment]:
        if not isinstance(raw_segment, dict):
            raise TypeError("transit segment must be an object")
        if raw_segment.get("taxi"):
            raise ValueError("taxi segments are not supported for local public transport")

        segments: list[RouteSegment] = []
        walking = raw_segment.get("walking")
        if walking:
            segments.append(AmapRouteService._to_walking_segment(walking))

        bus = raw_segment.get("bus")
        if bus:
            segments.extend(AmapRouteService._to_bus_segments(bus))

        railway = raw_segment.get("railway")
        if railway:
            segments.append(AmapRouteService._to_railway_segment(railway))
        return segments

    @staticmethod
    def _to_walking_segment(walking: object) -> RouteSegment:
        if not isinstance(walking, dict):
            raise TypeError("walking must be an object")
        steps = walking.get("steps")
        if not isinstance(steps, list):
            raise TypeError("walking steps must be a list")
        return RouteSegment(
            mode=RouteSegmentMode.WALKING,
            distance_meters=AmapRouteService._parse_nonnegative_int(walking.get("distance")),
            duration_seconds=AmapRouteService._parse_optional_nonnegative_int(
                walking.get("duration")
            ),
            polyline=AmapRouteService._merge_step_polylines(steps),
        )

    @staticmethod
    def _to_bus_segments(bus: object) -> list[RouteSegment]:
        if not isinstance(bus, dict):
            raise TypeError("bus must be an object")
        buslines = bus.get("buslines")
        if not isinstance(buslines, list):
            raise TypeError("buslines must be a list")

        segments: list[RouteSegment] = []
        for busline in buslines:
            if not isinstance(busline, dict):
                raise TypeError("busline must be an object")
            line_type = busline.get("type")
            if not isinstance(line_type, str):
                raise TypeError("busline type must be a string")
            raw_polyline = busline.get("polyline")
            segments.append(
                RouteSegment(
                    mode=(
                        RouteSegmentMode.SUBWAY
                        if "地铁" in line_type
                        else RouteSegmentMode.BUS
                    ),
                    distance_meters=AmapRouteService._parse_nonnegative_int(
                        busline.get("distance")
                    ),
                    duration_seconds=AmapRouteService._parse_optional_nonnegative_int(
                        busline.get("duration")
                    ),
                    polyline=(
                        AmapRouteService._parse_polyline(raw_polyline)
                        if raw_polyline is not None
                        else None
                    ),
                )
            )
        return segments

    @staticmethod
    def _to_railway_segment(railway: object) -> RouteSegment:
        if not isinstance(railway, dict):
            raise TypeError("railway must be an object")
        return RouteSegment(
            mode=RouteSegmentMode.RAILWAY,
            distance_meters=AmapRouteService._parse_nonnegative_int(railway.get("distance")),
            duration_seconds=AmapRouteService._parse_optional_nonnegative_int(
                railway.get("time")
            ),
            polyline=None,
        )

    @staticmethod
    def _merge_step_polylines(steps: list[object]) -> Polyline | None:
        if not steps:
            return None

        points = []
        for step in steps:
            if not isinstance(step, dict):
                raise TypeError("walking step must be an object")
            for point in AmapRouteService._parse_polyline(step.get("polyline")).points:
                if not points or point != points[-1]:
                    points.append(point)
        return Polyline(points=points)

    @staticmethod
    def _parse_polyline(value: object) -> Polyline:
        if isinstance(value, dict):
            value = value.get("polyline")
        if not isinstance(value, str):
            raise TypeError("polyline must be a string or an object containing a string")
        return parse_amap_polyline(value)

    @staticmethod
    def _to_driving_segment(step: object) -> RouteSegment:
        if not isinstance(step, dict):
            raise TypeError("step must be an object")
        polyline = step.get("polyline")
        if not isinstance(polyline, str):
            raise TypeError("step polyline must be a string")

        return RouteSegment(
            mode=RouteSegmentMode.DRIVING,
            distance_meters=AmapRouteService._parse_nonnegative_int(
                step.get("step_distance")
            ),
            duration_seconds=AmapRouteService._parse_duration(step.get("cost")),
            polyline=parse_amap_polyline(polyline),
        )

    @staticmethod
    def _parse_duration(cost: object) -> int:
        if not isinstance(cost, dict):
            raise TypeError("cost must be an object")
        return AmapRouteService._parse_nonnegative_int(cost.get("duration"))

    @staticmethod
    def _parse_optional_nonnegative_int(value: Any) -> int | None:
        if value is None:
            return None
        return AmapRouteService._parse_nonnegative_int(value)

    @staticmethod
    def _parse_nonnegative_int(value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("value must be an integer")
        if isinstance(value, int):
            parsed_value = value
        elif isinstance(value, str) and value.strip().isdigit():
            parsed_value = int(value.strip())
        else:
            raise ValueError("value must be an integer")
        if parsed_value < 0:
            raise ValueError("value must not be negative")
        return parsed_value
