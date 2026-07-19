from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness() -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}


def test_readiness(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.health.check_database", lambda: None)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api",
        "database": "ok",
    }


def test_readiness_reports_database_failure(monkeypatch) -> None:
    def fail() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.api.routes.health.check_database", fail)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_unavailable"
