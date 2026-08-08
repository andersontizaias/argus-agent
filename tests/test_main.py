from fastapi.testclient import TestClient

from src.main import app


def test_app_boots_and_serves_health():
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code in (200, 503)


def test_spa_fallback_serves_index_for_client_routes():
    """frontend/dist já existe (buildado via `npm run build`) — uma rota
    não-API deve cair no fallback do React Router, servindo index.html."""
    with TestClient(app) as client:
        resp = client.get("/some/client/route")
    assert resp.status_code == 200
    assert "root" in resp.text


def test_spa_assets_mounted():
    with TestClient(app) as client:
        resp = client.get("/img/logo.png")
    assert resp.status_code == 200
