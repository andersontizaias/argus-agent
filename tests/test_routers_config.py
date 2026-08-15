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
        })
        assert resp.status_code == 200
        resp = client.get("/api/config")
        assert resp.json()["anthropic_api_key"] == "sk-a****5678"


def test_save_and_retrieve_default_model_per_provider():
    # Modelo default é por provider, não um único global — configurar o do
    # Anthropic não deveria afetar o do Groq (e vice-versa).
    with _client() as client:
        resp = client.post("/api/config", json={
            "anthropic_default_model": "claude-3-5-haiku-latest",
            "groq_default_model": "llama-3.3-70b-versatile",
        })
        assert resp.status_code == 200

        resp = client.get("/api/config")
        body = resp.json()
        assert body["anthropic_default_model"] == "claude-3-5-haiku-latest"
        assert body["groq_default_model"] == "llama-3.3-70b-versatile"
        assert body["openai_default_model"] == ""


def test_short_secret_masked_fully():
    with _client() as client:
        client.post("/api/config", json={"anthropic_api_key": "short"})
        resp = client.get("/api/config")
    assert resp.json()["anthropic_api_key"] == "****"


def test_save_and_mask_ollama_api_key_roundtrip():
    # Regressão: needs_api_key=False (a chave do Ollama é opcional — só
    # necessária atrás de um reverse proxy com auth) fazia o save_config
    # pular a chave inteira com um `if not provider.needs_api_key: continue`
    # — preencher na UI nunca persistia nada, e o GET nem devolvia o campo.
    with _client() as client:
        resp = client.post("/api/config", json={"ollama_api_key": "meu-bearer-token-secreto"})
        assert resp.status_code == 200

        resp = client.get("/api/config")
        body = resp.json()
        assert "ollama_api_key" in body
        assert body["ollama_api_key"] == "meu-****reto"

        # Reenviar o placeholder mascarado preserva o valor salvo.
        client.post("/api/config", json={"ollama_api_key": body["ollama_api_key"]})
        resp = client.get("/api/config")
        assert resp.json()["ollama_api_key"] == "meu-****reto"


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


def test_partial_post_does_not_wipe_settings_omitted_from_the_body():
    # Bug real visto ao vivo: um POST /api/config com corpo {} (ou qualquer
    # corpo que não mande TODOS os campos — normal pra um caller de API que
    # não é a própria UI, que sempre reenvia o estado inteiro da tela)
    # resetava pra "" todo setting que não veio, silenciosamente. Campo
    # OMITIDO não deveria mexer no que já tava salvo — só um valor
    # explícito (mesmo "") deveria.
    with _client() as client:
        client.post("/api/config", json={
            "ollama_base_url": "https://ollama.example.com/",
            "bedrock_region": "us-east-1",
            "default_llm_provider": "ollama",
            "retention_days": "45",
        })

        resp = client.post("/api/config", json={})
        assert resp.status_code == 200

        resp = client.get("/api/config")
    body = resp.json()
    assert body["ollama_base_url"] == "https://ollama.example.com/"
    assert body["bedrock_region"] == "us-east-1"
    assert body["default_llm_provider"] == "ollama"
    assert body["retention_days"] == "45"


def test_explicit_empty_string_still_clears_a_setting():
    # Diferente do caso acima: um valor vazio EXPLÍCITO (o campo veio no
    # corpo, só que vazio) continua limpando o setting — é assim que a UI
    # limpa o "Provider default" (opção "Nenhum" no <select>). Só a
    # AUSÊNCIA do campo deveria ser ignorada, nunca "" mandado de propósito.
    with _client() as client:
        client.post("/api/config", json={"default_llm_provider": "ollama"})

        resp = client.post("/api/config", json={"default_llm_provider": ""})
        assert resp.status_code == 200

        resp = client.get("/api/config")
    assert resp.json()["default_llm_provider"] == ""


def test_save_and_retrieve_ollama_timeout_seconds():
    with _client() as client:
        resp = client.post("/api/config", json={"ollama_timeout_seconds": "600"})
        assert resp.status_code == 200
        resp = client.get("/api/config")
    assert resp.json()["ollama_timeout_seconds"] == "600"


def test_save_and_mask_bedrock_api_key_roundtrip():
    # Fluxo padrão do Bedrock: só a API key + região, mesmo caminho de
    # todo provider (secret_name genérico) — nenhuma configuração extra.
    # Valor claramente fake (não parece uma credencial real) — o mesmo
    # cuidado do "sk-fake-key-not-used" já usado em outros testes, pra não
    # disparar a regra de entropia genérica do gitleaks.
    with _client() as client:
        resp = client.post("/api/config", json={
            "bedrock_api_key": "fake-bedrock-key-not-used",
            "bedrock_region": "us-east-1",
        })
        assert resp.status_code == 200

        resp = client.get("/api/config")
        body = resp.json()
        assert body["bedrock_api_key"] == "fake****used"
        assert body["bedrock_region"] == "us-east-1"

        # Reenviar o placeholder mascarado preserva o valor salvo.
        client.post("/api/config", json={"bedrock_api_key": body["bedrock_api_key"], "bedrock_region": "us-east-1"})
        resp = client.get("/api/config")
        assert resp.json()["bedrock_api_key"] == "fake****used"


def test_save_and_mask_bedrock_sigv4_roundtrip():
    # Fluxo avançado: os 3 secrets SigV4 mascaram/preservam de forma
    # independente entre si, igual ao secret_name normal de outro provider.
    # Valores claramente fake (mesmo cuidado do teste acima) — evita parecer
    # uma AWS access key de verdade (formato "AKIA" + 16 chars) e disparar
    # a regra de entropia genérica do gitleaks.
    with _client() as client:
        resp = client.post("/api/config", json={
            "bedrock_access_key_id": "fake-aws-access-key-aaaa",
            "bedrock_secret_access_key": "fake-aws-secret-key-bbbb",
            "bedrock_session_token": "fake-aws-session-tok-cccc",
            "bedrock_region": "us-west-2",
        })
        assert resp.status_code == 200

        resp = client.get("/api/config")
        body = resp.json()
        assert body["bedrock_access_key_id"] == "fake****aaaa"
        assert body["bedrock_secret_access_key"] == "fake****bbbb"
        assert body["bedrock_session_token"] == "fake****cccc"
        assert body["bedrock_region"] == "us-west-2"

        # Reenviar os 3 placeholders mascarados preserva cada valor salvo.
        client.post("/api/config", json={
            "bedrock_access_key_id": body["bedrock_access_key_id"],
            "bedrock_secret_access_key": body["bedrock_secret_access_key"],
            "bedrock_session_token": body["bedrock_session_token"],
            "bedrock_region": "us-west-2",
        })
        resp = client.get("/api/config")
        body = resp.json()
        assert body["bedrock_access_key_id"] == "fake****aaaa"
        assert body["bedrock_secret_access_key"] == "fake****bbbb"
        assert body["bedrock_session_token"] == "fake****cccc"


def test_save_ollama_timeout_seconds_rejects_non_numeric():
    with _client() as client:
        resp = client.post("/api/config", json={"ollama_timeout_seconds": "abc"})
    assert resp.status_code == 400
    assert "whole number" in resp.json()["error"]


def test_test_llm_provider_unknown_returns_404():
    with _client() as client:
        resp = client.post("/api/config/test-llm-provider/nope")
    assert resp.status_code == 404


def test_test_llm_provider_not_configured_returns_400():
    with _client() as client:
        resp = client.post("/api/config/test-llm-provider/anthropic")
    assert resp.status_code == 400
    assert "isn't configured" in resp.json()["error"]


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


def test_test_llm_provider_uses_that_providers_configured_default_model(monkeypatch):
    # Regressão: testar sempre com o example_model fixo (ex.: "qwen2.5:14b"
    # pro Ollama) dá 404 "model not found" se esse modelo específico nunca
    # foi baixado no servidor do usuário — o teste deve usar o modelo que a
    # pessoa configurou como default PRA ESSE PROVIDER (não precisa ser o
    # "provider default" global).
    captured_models = []

    class _FakeModel:
        def invoke(self, _prompt):
            return "pong"

    def _fake_build(_provider_id, model, _api_key, **_kwargs):
        captured_models.append(model)
        return _FakeModel()

    monkeypatch.setattr("src.routers.config.build_chat_model", _fake_build)

    with _client() as client:
        client.post("/api/config", json={
            "ollama_base_url": "http://localhost:11434",
            "ollama_default_model": "meu-modelo-baixado-localmente",
        })
        resp = client.post("/api/config/test-llm-provider/ollama")

    assert resp.status_code == 200
    assert resp.json()["model"] == "meu-modelo-baixado-localmente"
    assert captured_models == ["meu-modelo-baixado-localmente"]


def test_test_llm_provider_ignores_default_model_of_a_different_provider(monkeypatch):
    class _FakeModel:
        def invoke(self, _prompt):
            return "pong"

    monkeypatch.setattr("src.routers.config.build_chat_model", lambda *a, **k: _FakeModel())

    with _client() as client:
        client.post("/api/config", json={
            "anthropic_api_key": "sk-ant-abcdefgh12345678",
            "openai_default_model": "gpt-5-nano",  # não é o provider sendo testado
        })
        resp = client.post("/api/config/test-llm-provider/anthropic")

    assert resp.status_code == 200
    assert resp.json()["model"] == "claude-3-5-haiku-latest"  # example_model do anthropic, não o default salvo


def test_test_llm_provider_connection_failure(monkeypatch):
    def _raise(*_a, **_k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("src.routers.config.build_chat_model", _raise)

    with _client() as client:
        client.post("/api/config", json={"anthropic_api_key": "sk-ant-abcdefgh12345678"})
        resp = client.post("/api/config/test-llm-provider/anthropic")
    assert resp.status_code == 400
    assert "connection refused" in resp.json()["error"]
