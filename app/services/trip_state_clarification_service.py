"""LLM wording for only the clarification topics determined by Python."""

import json
from dataclasses import asdict, dataclass

from app.schemas.trip_state import LocationIntent, LocationResolutionStatus
from app.schemas.trip_state_assessment import RequiredTripStateField
from app.schemas.trip_state_clarification import TripStateClarification
from app.services.llm_provider import (
    LlmMessage,
    LlmMessageRole,
    LlmProvider,
    LlmResponseError,
)
from app.services.trip_state_update_service import TripStateUpdateResult


CLARIFICATION_INSTRUCTIONS = """Write one concise Chinese question for every topic.
Use every topic_id exactly once and preserve their order. Ask only for the information
described by each topic. Do not recommend destinations, hotels, attractions, routes,
or transportation. Do not invent candidates or map facts."""


@dataclass(frozen=True)
class _ClarificationTopic:
    topic_id: str
    instruction: str
    candidates: list[dict[str, str | None]] | None = None


class TripStateClarificationService:
    """Generate validated Chinese wording for deterministic clarification needs."""

    def __init__(self, provider: LlmProvider) -> None:
        self._provider = provider

    def generate(self, update_result: TripStateUpdateResult) -> TripStateClarification:
        """Return no questions when ready, otherwise word exactly the required topics."""
        topics = self._build_topics(update_result)
        if not topics:
            return TripStateClarification()

        messages = [
            LlmMessage(role=LlmMessageRole.SYSTEM, content=CLARIFICATION_INSTRUCTIONS),
            LlmMessage(
                role=LlmMessageRole.USER,
                content="Clarification topics JSON:\n"
                + json.dumps(
                    [asdict(topic) for topic in topics],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        ]
        clarification = self._provider.generate_structured(messages, TripStateClarification)
        expected_topic_ids = [topic.topic_id for topic in topics]
        actual_topic_ids = [question.topic_id for question in clarification.questions]
        if actual_topic_ids != expected_topic_ids:
            raise LlmResponseError("LLM clarification topics do not match the required topics")
        return clarification

    def _build_topics(self, update_result: TripStateUpdateResult) -> list[_ClarificationTopic]:
        topics = [
            _ClarificationTopic(
                topic_id=f"missing:{field.value}",
                instruction=self._missing_instruction(field),
            )
            for field in update_result.assessment.missing_fields
        ]
        failures = {
            (failure.field, failure.place_index): failure
            for failure in update_result.location_failures
        }
        for pending in update_result.assessment.pending_locations:
            location = self._get_location(update_result, pending.field, pending.place_index)
            suffix = "" if pending.place_index is None else f":{pending.place_index}"
            failure = failures.get((pending.field.value, pending.place_index))
            if pending.resolution_status is LocationResolutionStatus.AMBIGUOUS:
                topics.append(
                    _ClarificationTopic(
                        topic_id=f"confirm:{pending.field.value}{suffix}",
                        instruction=f"Ask the user to choose the intended location for {pending.query}.",
                        candidates=self._candidate_context(location),
                    )
                )
            else:
                error_context = "" if failure is None else f" Map lookup failed with {failure.error_code}."
                topics.append(
                    _ClarificationTopic(
                        topic_id=f"refine:{pending.field.value}{suffix}",
                        instruction=(
                            f"Ask the user for a more specific location for {pending.query}."
                            + error_context
                        ),
                    )
                )
        return topics

    @staticmethod
    def _missing_instruction(field: RequiredTripStateField) -> str:
        return {
            RequiredTripStateField.ORIGIN: "Ask for the actual departure location.",
            RequiredTripStateField.DESTINATION: "Ask for the travel destination.",
            RequiredTripStateField.RETURN_DESTINATION: "Ask for the final return location.",
            RequiredTripStateField.DEPARTURE_DATE: "Ask for the departure date.",
            RequiredTripStateField.RETURN_DATE: "Ask for the return date.",
            RequiredTripStateField.ACCOMMODATION: "Ask for the accommodation location.",
            RequiredTripStateField.PLACES: "Ask for at least one place the user wants to visit.",
            RequiredTripStateField.INTERCITY_TRAVEL_MODE: "Ask for the specific intercity travel mode, such as driving, high-speed rail, train, or flight.",
            RequiredTripStateField.LOCAL_TRAVEL_MODE: "Ask whether local travel uses driving or public transport.",
            RequiredTripStateField.VEHICLE: "Ask for the vehicle energy type and range.",
        }[field]

    @staticmethod
    def _get_location(
        update_result: TripStateUpdateResult,
        field: RequiredTripStateField,
        place_index: int | None,
    ) -> LocationIntent:
        if field is RequiredTripStateField.ORIGIN:
            assert update_result.state.origin is not None
            return update_result.state.origin
        if field is RequiredTripStateField.DESTINATION:
            assert update_result.state.destination is not None
            return update_result.state.destination
        if field is RequiredTripStateField.RETURN_DESTINATION:
            assert update_result.state.return_destination is not None
            return update_result.state.return_destination
        if field is RequiredTripStateField.ACCOMMODATION:
            assert update_result.state.accommodation is not None
            return update_result.state.accommodation
        assert place_index is not None
        return update_result.state.places[place_index]

    @staticmethod
    def _candidate_context(location: LocationIntent) -> list[dict[str, str | None]]:
        return [
            {"poi_id": candidate.poi_id, "name": candidate.name, "address": candidate.address}
            for candidate in location.candidates
        ]
