from fastapi import FastAPI

from app.api.trips import router as trips_router


app = FastAPI(title="TravelAgent API")
app.include_router(trips_router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return the service liveness status."""
    return {"status": "ok"}
