from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.trip import create_empty_trip, create_trip, get_trip_by_id
from app.repositories.trip_plan import get_trip_plan, save_trip_plan
from app.repositories.trip_state import get_trip_state
from app.schemas.trip_location_confirmation import (
    TripLocationConfirmationCreate,
    TripLocationConfirmationRead,
)
from app.schemas.trip_conversation import (
    LocationResolutionFailureRead,
    TripConversationCreateRead,
    TripConversationRead,
    TripMessageCreate,
)
from app.schemas.trip import TripCreate, TripRead, TripUpdate
from app.schemas.trip_public_transport_plan import (
    PublicTransportPlanningRequest,
    PublicTransportTripPlan,
)
from app.core.config import get_settings
from app.services.amap_api_service import AmapApiService
from app.services.llm_provider import LlmConfigurationError, LlmProviderError
from app.services.llm_provider_factory import create_llm_provider
from app.services.map_errors import (
    MapConfigurationError,
    MapNoResultsError,
    MapQuotaExceededError,
    MapServiceError,
    MapTimeoutError,
    MapUpstreamError,
)
from app.services.public_transport_trip_planning_service import (
    PublicTransportTripPlanningService,
)
from app.services.trip_state_clarification_service import TripStateClarificationService
from app.services.trip_state_conversation_service import TripStateConversationService
from app.services.trip_state_conversation_service import TripStateConversationResult
from app.services.trip_state_extraction_service import TripStateExtractionService
from app.services.trip_state_location_resolution_service import (
    TripStateLocationResolutionService,
)
from app.services.trip_state_location_confirmation_service import (
    TripStateLocationConfirmationService,
)
from app.services.trip_state_update_service import TripStateUpdateService
from app.services.trip_update_service import TripUpdateService


router = APIRouter(prefix="/trips", tags=["trips"])


def get_trip_state_conversation_service() -> TripStateConversationService:
    """Construct the Stage 2 conversation flow from configured adapters."""
    try:
        settings = get_settings()
        provider = create_llm_provider(settings)
    except LlmConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trip conversation service is unavailable",
        ) from error
    extractor = TripStateExtractionService(provider)
    amap_service = AmapApiService(settings.amap_web_api_key)
    location_resolver = TripStateLocationResolutionService(amap_service)
    location_confirmer = TripStateLocationConfirmationService(amap_service)
    updater = TripStateUpdateService(extractor, location_resolver, location_confirmer)
    clarifier = TripStateClarificationService(provider)
    return TripStateConversationService(updater, clarifier)


def get_trip_state_location_confirmation_service() -> TripStateLocationConfirmationService:
    """Construct the Amap-backed confirmation capability for a TripState location."""
    settings = get_settings()
    return TripStateLocationConfirmationService(AmapApiService(settings.amap_web_api_key))


def get_public_transport_trip_planning_service() -> PublicTransportTripPlanningService:
    """Construct the Stage 3 planner from the configured Stage 1 map adapter."""
    settings = get_settings()
    return PublicTransportTripPlanningService(AmapApiService(settings.amap_web_api_key))


def _conversation_read(result: TripStateConversationResult) -> TripConversationRead:
    """Translate the service result without exposing provider or map internals."""
    return TripConversationRead(
        state=result.state,
        location_failures=[
            LocationResolutionFailureRead(
                field=failure.field,
                query=failure.query,
                error_code=failure.error_code,
                place_index=failure.place_index,
            )
            for failure in result.location_failures
        ],
        assessment=result.assessment,
        clarification=result.clarification,
    )


@router.post("/conversations", response_model=TripConversationCreateRead, status_code=status.HTTP_201_CREATED)
def create_trip_from_first_message_endpoint(
    trip_message: TripMessageCreate,
    session: Session = Depends(get_db),
    conversation_service: TripStateConversationService = Depends(
        get_trip_state_conversation_service
    ),
) -> TripConversationCreateRead:
    """Create a Trip and persist its first natural-language state update atomically."""
    trip = create_empty_trip(session)
    try:
        result = conversation_service.handle(
            session, trip.id, trip_message.message, commit=False
        )
        session.commit()
        session.refresh(trip)
    except LlmConfigurationError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trip conversation service is unavailable",
        ) from error
    except LlmProviderError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Trip conversation could not be processed",
        ) from error
    except (ValidationError, ValueError) as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Trip conversation update is invalid",
        ) from error

    conversation_read = _conversation_read(result)
    return TripConversationCreateRead(
        trip=TripRead.model_validate(trip),
        **conversation_read.model_dump(),
    )


@router.post("", response_model=TripRead, status_code=status.HTTP_201_CREATED)
def create_trip_endpoint(
    trip_data: TripCreate,
    session: Session = Depends(get_db),
) -> TripRead:
    """Create a new independent travel plan."""
    return create_trip(session, trip_data)


@router.get("/{trip_id}", response_model=TripRead)
def get_trip_endpoint(trip_id: UUID, session: Session = Depends(get_db)) -> TripRead:
    """Return one persisted travel plan."""
    trip = get_trip_by_id(session, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    return trip


@router.patch("/{trip_id}", response_model=TripRead)
def update_trip_endpoint(
    trip_id: UUID,
    trip_data: TripUpdate,
    session: Session = Depends(get_db),
) -> TripRead:
    """Partially update one persisted travel plan."""
    trip = get_trip_by_id(session, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")

    try:
        return TripUpdateService().update(session, trip, trip_data)
    except ValueError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error


@router.post(
    "/{trip_id}/public-transport-plan",
    response_model=PublicTransportTripPlan,
    status_code=status.HTTP_201_CREATED,
)
def create_public_transport_trip_plan_endpoint(
    trip_id: UUID,
    planning_request: PublicTransportPlanningRequest,
    session: Session = Depends(get_db),
    planning_service: PublicTransportTripPlanningService = Depends(
        get_public_transport_trip_planning_service
    ),
) -> PublicTransportTripPlan:
    """Generate and save the current complete public-transport plan for one Trip."""
    if planning_request.trip_id != trip_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Planning request trip_id must match path",
        )
    if get_trip_by_id(session, trip_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    state = get_trip_state(session, trip_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TripState has not been created",
        )

    try:
        plan = planning_service.plan(state, planning_request)
        return save_trip_plan(session, plan)
    except MapNoResultsError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No public transport route is available for this plan",
        ) from error
    except MapTimeoutError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Public transport route request timed out",
        ) from error
    except (MapConfigurationError, MapQuotaExceededError) as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public transport planning service is unavailable",
        ) from error
    except (MapUpstreamError, MapServiceError) as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Public transport map service is unavailable",
        ) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Public transport plan is invalid",
        ) from error


@router.get("/{trip_id}/public-transport-plan", response_model=PublicTransportTripPlan)
def get_public_transport_trip_plan_endpoint(
    trip_id: UUID,
    session: Session = Depends(get_db),
) -> PublicTransportTripPlan:
    """Return the current saved public-transport plan without regenerating it."""
    if get_trip_by_id(session, trip_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    plan = get_trip_plan(session, trip_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Public transport plan has not been generated",
        )
    return plan


@router.post("/{trip_id}/messages", response_model=TripConversationRead)
def handle_trip_message_endpoint(
    trip_id: UUID,
    trip_message: TripMessageCreate,
    session: Session = Depends(get_db),
    conversation_service: TripStateConversationService = Depends(
        get_trip_state_conversation_service
    ),
) -> TripConversationRead:
    """Apply one natural-language message to an existing persisted TripState."""
    if get_trip_by_id(session, trip_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")

    try:
        result = conversation_service.handle(session, trip_id, trip_message.message)
    except LlmConfigurationError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trip conversation service is unavailable",
        ) from error
    except LlmProviderError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Trip conversation could not be processed",
        ) from error
    except (ValidationError, ValueError) as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Trip conversation update is invalid",
        ) from error

    return _conversation_read(result)


@router.post("/{trip_id}/locations/confirm", response_model=TripLocationConfirmationRead)
def confirm_trip_location_endpoint(
    trip_id: UUID,
    confirmation: TripLocationConfirmationCreate,
    session: Session = Depends(get_db),
    confirmation_service: TripStateLocationConfirmationService = Depends(
        get_trip_state_location_confirmation_service
    ),
) -> TripLocationConfirmationRead:
    """Persist an Amap-confirmed choice from a previously ambiguous location."""
    if get_trip_by_id(session, trip_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")

    try:
        state, assessment = confirmation_service.confirm(
            session,
            trip_id,
            field=confirmation.field,
            selected_poi_id=confirmation.poi_id,
            place_index=confirmation.place_index,
        )
    except LookupError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TripState has not been created",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except MapServiceError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Location confirmation could not be completed",
        ) from error

    return TripLocationConfirmationRead(state=state, assessment=assessment)
