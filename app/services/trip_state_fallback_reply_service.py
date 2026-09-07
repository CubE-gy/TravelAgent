"""Fact-based replies used only when an LLM turn cannot be completed."""

from app.schemas.trip_state import LocationResolutionStatus, TripState


def reply_from_trip_state(state: TripState) -> str:
    """Answer from persisted facts without inferring intent or mutating the Trip."""
    accommodation = state.accommodation
    if accommodation is None:
        return "目前还没有记录酒店。你可以告诉我酒店名称、所在区域或地址，我会帮你确认并标记到地图上。"
    if accommodation.resolution_status is LocationResolutionStatus.RESOLVED:
        name = (
            accommodation.resolved_location.name
            if accommodation.resolved_location is not None
            else accommodation.query
        )
        return f"酒店已确定为「{name}」。你可以继续补充景点、交通或其他偏好。"
    return (
        f"酒店地点「{accommodation.query}」还未确认。"
        "请补充酒店完整名称、所在区域或地址，我会据此确认地图位置。"
    )
