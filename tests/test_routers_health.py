from fastapi.testclient import TestClient

from src.doctor import CheckResult
from src.main import app


def test_health_ok_when_all_checks_pass(monkeypatch):
    monkeypatch.setattr(
        "src.routers.health.run_checks",
        lambda: [CheckResult("database", True, "ok")],
    )
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]  # veio do pyproject.toml via importlib.metadata, nunca hardcoded


def test_health_degraded_when_a_check_fails(monkeypatch):
    monkeypatch.setattr(
        "src.routers.health.run_checks",
        lambda: [CheckResult("database", True, "ok"), CheckResult("appium", False, "not found")],
    )
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert any(c["name"] == "appium" and not c["ok"] for c in body["checks"])
