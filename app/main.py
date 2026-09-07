from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.trips import router as trips_router
from app.core.config import get_settings


app = FastAPI(title="TravelAgent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(trips_router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return the service liveness status."""
    return {"status": "ok"}
