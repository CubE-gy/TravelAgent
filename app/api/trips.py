from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.error_mapping import map_map_service_error
from app.db.session import get_db
from app.repositories.trip import create_empty_trip, create_trip, get_trip_by_id, list_trips
from app.repositories.trip_plan import (
    TripPlanStateRevisionConflictError,
    get_trip_plan,
    save_trip_plan,
)
from app.repositories.trip_state import TripStateRevisionConflictError, get_trip_state
from app.repositories.trip_memory import list_trip_memories
from app.schemas.trip_location_confirmation import (
    TripLocationConfirmationCreate,
    TripLocationConfirmationRead,
)
from app.schemas.trip_conversation import (
    LocationResolutionFailureRead,
    TripConversationCreate,
    TripConversationCreateRead,
    TripConversationRead,
    TripMessageCreate,
)
from app.schemas.trip import TripCreate, TripRead, TripUpdate
from app.schemas.trip_public_transport_plan import (
    PublicTransportPlanningRequest,
    PublicTransportTripPlan,
    PublicTransportTripPlanRead,
)
from app.schemas.trip_workspace import TripWorkspaceRead
from app.schemas.trip_recommendation import TripRecommendationSelection
from app.core.config import get_settings
from app.services.amap_api_service import AmapApiService
from app.services.llm_provider import LlmConfigurationError, LlmProviderError
from app.services.llm_provider_factory import create_llm_provider
from app.services.llm_call_tracer import TracingLlmProvider
from app.services.trip_turn_store import TripTurnStore
from app.services.map_errors import MapServiceError
from app.services.public_transport_trip_planning_service import (
    PublicTransportTripPlanningService,
)
from app.services.trip_state_clarification_service import TripStateClarificationService
from app.schemas.trip_state_clarification import TripStateClarification
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
from app.services.trip_agent_reply_service import TripAgentReplyService
from app.services.travel_manager_agent import TravelManagerAgent
from app.services.travel_tool import SearchRecommendationsTool, UpdateTripStateTool
from app.services.travel_tool_registry import TravelToolRegistry
from app.services.validation_retrying_llm_provider import ValidationRetryingLlmProvider
from app.services.trip_recommendation_service import TripRecommendationService
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
    tracing_provider = TracingLlmProvider(provider)
    retrying_provider = ValidationRetryingLlmProvider(tracing_provider)
    extractor = TripStateExtractionService(retrying_provider)
    amap_service = AmapApiService(settings.amap_web_api_key)
    location_resolver = TripStateLocationResolutionService(amap_service, city_service=amap_service, auto_select=True)
    location_confirmer = TripStateLocationConfirmationService(amap_service)
    updater = TripStateUpdateService(
        extractor, location_resolver, location_confirmer, memory_reader=list_trip_memories
    )
    clarifier = TripStateClarificationService(tracing_provider, workspace_mode=True)
    recommendation_service = TripRecommendationService(amap_service)
    tool_registry = TravelToolRegistry([
        UpdateTripStateTool(updater),
        SearchRecommendationsTool(recommendation_service),
    ])
    reply_generator = TripAgentReplyService(retrying_provider)
    manager_agent = TravelManagerAgent(extractor, reply_generator, tool_registry)
    return TripStateConversationService(
        updater, clarifier, reply_generator, manager_agent=manager_agent,
        turn_store=TripTurnStore(tracing_provider),
    )


def get_trip_recommendation_service() -> TripRecommendationService:
    settings = get_settings()
    return TripRecommendationService(AmapApiService(settings.amap_web_api_key))


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
        revision=result.state.revision,
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
        assistant_message=result.assistant_message,
        recommendations=result.recommendations or [],
        recommendation_session_id=result.recommendation_session_id,
    )


def _conversation_context(context: list[object]) -> list[dict[str, str]]:
    """Pass bounded browser history separately from the current authorization."""
    return [item.model_dump() for item in context]


def _public_transport_plan_read(
    plan: PublicTransportTripPlan, state: object | None
) -> PublicTransportTripPlanRead:
    """Expose freshness without persisting a derived status on the plan snapshot."""
    state_revision = getattr(state, "revision", None)
    return PublicTransportTripPlanRead(
        **plan.model_dump(),
        stale=state_revision != plan.source_state_revision,
    )


@router.post("/conversations", response_model=TripConversationCreateRead, status_code=status.HTTP_201_CREATED)
def create_trip_from_first_message_endpoint(
    trip_message: TripConversationCreate,
    session: Session = Depends(get_db),
    conversation_service: TripStateConversationService = Depends(
        get_trip_state_conversation_service
    ),
) -> TripConversationCreateRead:
    """Create a Trip and persist its first natural-language state update atomically."""
    trip = create_empty_trip(session)
    try:
        handle_args = dict(expected_revision=0, commit=False)
        if trip_message.conversation_context:
            handle_args["conversation_context"] = _conversation_context(trip_message.conversation_context)
        if trip_message.recommendation_context is not None:
            handle_args["recommendation_context"] = trip_message.recommendation_context
        result = conversation_service.handle(session, trip.id, trip_message.message, **handle_args)
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


@router.get("", response_model=list[TripRead])
def list_trips_endpoint(session: Session = Depends(get_db)) -> list[TripRead]:
    """Return all saved travel plans, newest update first."""
    return list_trips(session)


@router.get("/{trip_id}", response_model=TripRead)
def get_trip_endpoint(trip_id: UUID, session: Session = Depends(get_db)) -> TripRead:
    """Return one persisted travel plan."""
    trip = get_trip_by_id(session, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    return trip


@router.get("/{trip_id}/workspace", response_model=TripWorkspaceRead)
def get_trip_workspace_endpoint(
    trip_id: UUID, session: Session = Depends(get_db)
) -> TripWorkspaceRead:
    """Return persisted Trip facts needed to restore the Stage 4 map workspace."""
    trip = get_trip_by_id(session, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    state = get_trip_state(session, trip_id)
    plan = get_trip_plan(session, trip_id)
    return TripWorkspaceRead(
        trip=TripRead.model_validate(trip),
        state=state,
        public_transport_plan=(
            _public_transport_plan_read(plan, state) if plan is not None else None
        ),
    )


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
    except TripStateRevisionConflictError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TripState revision is stale",
        ) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error


@router.post(
    "/{trip_id}/public-transport-plan",
    response_model=PublicTransportTripPlanRead,
    status_code=status.HTTP_201_CREATED,
)
def create_public_transport_trip_plan_endpoint(
    trip_id: UUID,
    planning_request: PublicTransportPlanningRequest,
    session: Session = Depends(get_db),
    planning_service: PublicTransportTripPlanningService = Depends(
        get_public_transport_trip_planning_service
    ),
) -> PublicTransportTripPlanRead:
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
        return _public_transport_plan_read(
            save_trip_plan(
                session, plan, expected_state_revision=plan.source_state_revision
            ),
            state,
        )
    except TripPlanStateRevisionConflictError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TripState changed while public transport plan was being generated",
        ) from error
    except MapServiceError as error:
        session.rollback()
        raise map_map_service_error(
            error,
            no_results_detail="No public transport route is available for this plan",
            unavailable_detail="Public transport planning service is unavailable",
            timeout_detail="Public transport route request timed out",
            upstream_detail="Public transport map service is unavailable",
        ) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Public transport plan is invalid",
        ) from error


@router.get("/{trip_id}/public-transport-plan", response_model=PublicTransportTripPlanRead)
def get_public_transport_trip_plan_endpoint(
    trip_id: UUID,
    session: Session = Depends(get_db),
) -> PublicTransportTripPlanRead:
    """Return the current saved public-transport plan without regenerating it."""
    if get_trip_by_id(session, trip_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    plan = get_trip_plan(session, trip_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Public transport plan has not been generated",
        )
    return _public_transport_plan_read(plan, get_trip_state(session, trip_id))


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
        handle_args = dict(expected_revision=trip_message.expected_revision)
        if trip_message.conversation_context:
            handle_args["conversation_context"] = _conversation_context(trip_message.conversation_context)
        if trip_message.recommendation_context is not None:
            handle_args["recommendation_context"] = trip_message.recommendation_context
        result = conversation_service.handle(session, trip_id, trip_message.message, **handle_args)
    except TripStateRevisionConflictError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TripState revision is stale",
        ) from error
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


@router.post("/{trip_id}/recommendations/select", response_model=TripConversationRead)
def select_trip_recommendation_endpoint(
    trip_id: UUID,
    selection: TripRecommendationSelection,
    session: Session = Depends(get_db),
    recommendation_service: TripRecommendationService = Depends(get_trip_recommendation_service),
) -> TripConversationRead:
    """Persist the user's explicit click on a real, destination-city POI."""
    if get_trip_by_id(session, trip_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    state = get_trip_state(session, trip_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="TripState has not been created")
    try:
        result = recommendation_service.select(
            session, trip_id, state, kind=selection.kind, poi_id=selection.poi_id,
            expected_revision=selection.expected_revision,
            recommendation_session_id=selection.recommendation_session_id,
        )
        session.commit()
    except TripStateRevisionConflictError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="TripState revision is stale") from error
    except (ValueError, ValidationError) as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except MapServiceError as error:
        session.rollback()
        raise map_map_service_error(error, no_results_detail="Recommendation could not be confirmed",
            unavailable_detail="Recommendation service is unavailable", timeout_detail="Recommendation request timed out",
            upstream_detail="Recommendation service is unavailable") from error
    return _conversation_read(TripStateConversationResult(
        state=result.state, location_failures=result.location_failures,
        assessment=result.assessment, clarification=TripStateClarification(),
        assistant_message="已确认该地点，地图已更新。", recommendations=[],
    ))


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
            expected_revision=confirmation.expected_revision,
        )
    except TripStateRevisionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TripState revision is stale",
        ) from error
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
        raise map_map_service_error(
            error,
            no_results_detail="Location confirmation could not be completed",
            unavailable_detail="Location confirmation could not be completed",
            timeout_detail="Location confirmation could not be completed",
            upstream_detail="Location confirmation could not be completed",
        ) from error

    return TripLocationConfirmationRead(
        state=state,
        revision=state.revision,
        assessment=assessment,
    )
