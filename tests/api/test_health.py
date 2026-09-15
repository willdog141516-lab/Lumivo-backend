from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_health_reports_fixture_modes():
    client = TestClient(create_app(Settings()))

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Lumivo Backend",
        "environment": "development",
        "provider_mode": "fixture",
        "map_mode": "mock",
        "model_mode": "mock",
    }


def test_health_reflects_full_real_configuration():
    settings = Settings(provider_mode="full-real", frontend_origin="http://localhost:8989")
    response = TestClient(create_app(settings)).get("/api/v1/health")

    assert response.json()["map_mode"] == "baidu"
    assert response.json()["model_mode"] == "real"


def test_health_reflects_map_real_as_a_real_provider_mode():
    settings = Settings(provider_mode="map-real")

    response = TestClient(create_app(settings)).get("/api/v1/health")

    assert response.json()["map_mode"] == "baidu"
    assert response.json()["model_mode"] == "real"


def test_cors_allows_the_configured_frontend_origin():
    settings = Settings(frontend_origin="http://localhost:3100")
    response = TestClient(create_app(settings)).get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3100"},
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:3100"
