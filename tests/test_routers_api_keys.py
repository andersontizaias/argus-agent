from fastapi.testclient import TestClient

from src.main import app


def _client():
    return TestClient(app)


def test_create_api_key_returns_full_key_once():
    with _client() as client:
        resp = client.post("/api/api-keys", json={"name": "ci-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "ci-token"
    assert body["key"].startswith("argus_")
    assert body["prefix"] in body["key"]


def test_create_api_key_rejects_blank_name():
    with _client() as client:
        resp = client.post("/api/api-keys", json={"name": "   "})
    assert resp.status_code == 400


def test_list_api_keys_never_returns_the_full_key():
    with _client() as client:
        client.post("/api/api-keys", json={"name": "ci-token"})
        resp = client.get("/api/api-keys")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert "key" not in body[0]
    assert body[0]["name"] == "ci-token"
    assert body[0]["revoked"] is False


def test_revoke_api_key():
    with _client() as client:
        created = client.post("/api/api-keys", json={"name": "ci-token"}).json()
        resp = client.delete(f"/api/api-keys/{created['id']}")
        assert resp.status_code == 200

        listed = client.get("/api/api-keys").json()
    assert listed[0]["revoked"] is True


def test_revoke_unknown_api_key_returns_404():
    with _client() as client:
        resp = client.delete("/api/api-keys/does-not-exist")
    assert resp.status_code == 404


def test_api_keys_require_auth_off_loopback(monkeypatch):
    from src import auth

    monkeypatch.setattr(auth, "IS_LOOPBACK", False)
    with _client() as client:
        resp = client.get("/api/api-keys")
    assert resp.status_code == 401


def test_revoked_key_no_longer_authenticates(monkeypatch):
    from src import auth

    with _client() as client:
        created = client.post("/api/api-keys", json={"name": "ci-token"}).json()
        client.delete(f"/api/api-keys/{created['id']}")

    monkeypatch.setattr(auth, "IS_LOOPBACK", False)
    with _client() as client:
        resp = client.get("/api/api-keys", headers={"X-API-Key": created["key"]})
    assert resp.status_code == 401
