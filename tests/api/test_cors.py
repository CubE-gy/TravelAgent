from fastapi.testclient import TestClient

from app.main import app


def test_cors_allows_configured_vite_origin() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_unconfigured_origin() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"Origin": "https://untrusted.example.test"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_handles_preflight_for_trip_messages() -> None:
    client = TestClient(app)

    response = client.options(
        "/trips/example/messages",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]
