from fastapi.testclient import TestClient

from src.main import app


def _client():
    return TestClient(app)


def test_get_config_empty_by_default():
    with _client() as client:
        resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["anthropic_api_key"] == ""
    assert body["default_llm_provider"] == ""


def test_save_and_mask_secret_roundtrip():
    with _client() as client:
        resp = client.post("/api/config", json={
            "anthropic_api_key": "sk-ant-abcdefgh12345678",
            "default_llm_provider": "anthropic",
            "default_llm_model": "claude-3-5-haiku-latest",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        resp = client.get("/api/config")
        body = resp.json()
        assert body["anthropic_api_key"] == "sk-a****5678"
        assert body["default_llm_provider"] == "anthropic"

        # Reenviar o placeholder mascarado não deve sobrescrever o valor salvo.
        resp = client.post("/api/config", json={
            "anthropic_api_key": body["anthropic_api_key"],
            "default_llm_provider": "anthropic",
            "default_llm_model": "claude-3-5-haiku-latest",
        })
        assert resp.status_code == 200
        resp = client.get("/api/config")
        assert resp.json()["anthropic_api_key"] == "sk-a****5678"


def test_short_secret_masked_fully():
    with _client() as client:
        client.post("/api/config", json={"anthropic_api_key": "short"})
        resp = client.get("/api/config")
    assert resp.json()["anthropic_api_key"] == "****"


def test_save_base_urls_and_settings():
    with _client() as client:
        client.post("/api/config", json={
            "ollama_base_url": "http://localhost:11434",
            "custom_llm_base_url": "http://localhost:8080/v1",
        })
        resp = client.get("/api/config")
    body = resp.json()
    assert body["ollama_base_url"] == "http://localhost:11434"
    assert body["custom_llm_base_url"] == "http://localhost:8080/v1"


def test_save_and_retrieve_ollama_timeout_seconds():
    with _client() as client:
        resp = client.post("/api/config", json={"ollama_timeout_seconds": "600"})
        assert resp.status_code == 200
        resp = client.get("/api/config")
    assert resp.json()["ollama_timeout_seconds"] == "600"


def test_save_ollama_timeout_seconds_rejects_non_numeric():
    with _client() as client:
        resp = client.post("/api/config", json={"ollama_timeout_seconds": "abc"})
    assert resp.status_code == 400
    assert "número inteiro" in resp.json()["error"]


def test_test_llm_provider_unknown_returns_404():
    with _client() as client:
        resp = client.post("/api/config/test-llm-provider/nope")
    assert resp.status_code == 404


def test_test_llm_provider_not_configured_returns_400():
    with _client() as client:
        resp = client.post("/api/config/test-llm-provider/anthropic")
    assert resp.status_code == 400
    assert "não está configurado" in resp.json()["error"]


def test_test_llm_provider_success(monkeypatch):
    class _FakeModel:
        def invoke(self, _prompt):
            return "pong"

    monkeypatch.setattr("src.routers.config.build_chat_model", lambda *a, **k: _FakeModel())

    with _client() as client:
        client.post("/api/config", json={"anthropic_api_key": "sk-ant-abcdefgh12345678"})
        resp = client.post("/api/config/test-llm-provider/anthropic")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["provider"] == "anthropic"


def test_test_llm_provider_connection_failure(monkeypatch):
    def _raise(*_a, **_k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("src.routers.config.build_chat_model", _raise)

    with _client() as client:
        client.post("/api/config", json={"anthropic_api_key": "sk-ant-abcdefgh12345678"})
        resp = client.post("/api/config/test-llm-provider/anthropic")
    assert resp.status_code == 400
    assert "connection refused" in resp.json()["error"]
