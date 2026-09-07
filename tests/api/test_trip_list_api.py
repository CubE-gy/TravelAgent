from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


def test_list_trips_returns_saved_trips_in_repository_order(monkeypatch) -> None:
    newer_id, older_id = uuid4(), uuid4()
    timestamp = datetime(2026, 9, 6, tzinfo=timezone.utc)
    saved_trips = [
        SimpleNamespace(id=newer_id, name="南京周末", start_date=None, end_date=None, created_at=timestamp, updated_at=timestamp),
        SimpleNamespace(id=older_id, name=None, start_date=None, end_date=None, created_at=timestamp, updated_at=timestamp),
    ]
    monkeypatch.setattr("app.api.trips.list_trips", lambda session: saved_trips)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get("/trips")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(newer_id), str(older_id)]
    assert response.json()[0]["name"] == "南京周末"
