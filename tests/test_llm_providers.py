import pytest

from src import llm_providers, store


def test_get_provider_known_and_unknown():
    assert llm_providers.get_provider("anthropic") is not None
    assert llm_providers.get_provider("nope") is None


def test_is_provider_configured_false_when_missing_key():
    assert llm_providers.is_provider_configured("anthropic") is False


def test_is_provider_configured_true_after_setting_key():
    store.set_secret("anthropic_api_key", "enc-value")
    assert llm_providers.is_provider_configured("anthropic") is True


def test_is_provider_configured_false_for_unknown_provider():
    assert llm_providers.is_provider_configured("nope") is False


def test_is_provider_configured_requires_base_url_for_ollama():
    # needs_api_key=False, mas sem base_url configurada ainda falha.
    assert llm_providers.is_provider_configured("ollama") is False
    store.set_setting("ollama_base_url", "http://localhost:11434")
    assert llm_providers.is_provider_configured("ollama") is True


def test_build_chat_model_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        llm_providers.build_chat_model("nope", "model", "key")


def test_build_chat_model_ollama_without_base_url_raises():
    store.set_setting("ollama_base_url", "")
    with pytest.raises(ValueError, match="base URL"):
        llm_providers.build_chat_model("ollama", "qwen2.5:14b", "")


def test_build_chat_model_ollama_returns_chat_openai():
    from langchain_openai import ChatOpenAI

    store.set_setting("ollama_base_url", "http://localhost:11434/v1")
    model = llm_providers.build_chat_model("ollama", "qwen2.5:14b", "")
    assert isinstance(model, ChatOpenAI)


def test_build_chat_model_anthropic_returns_chat_model():
    from langchain_anthropic import ChatAnthropic

    model = llm_providers.build_chat_model("anthropic", "claude-3-5-haiku-latest", "sk-ant-fake")
    assert isinstance(model, ChatAnthropic)


def test_build_chat_model_ollama_sets_num_ctx_and_remote_base_url():
    # base_url remoto (não-localhost) — mesmo caminho de código de um
    # servidor local, prova que não há acoplamento a "127.0.0.1"/"localhost".
    store.set_setting("ollama_base_url", "http://192.168.1.50:11434/v1")
    model = llm_providers.build_chat_model("ollama", "qwen2.5:14b", "")
    assert model.openai_api_base == "http://192.168.1.50:11434/v1"
    assert model.extra_body == {"options": {"num_ctx": llm_providers.OLLAMA_NUM_CTX}}


def test_build_chat_model_custom_does_not_set_num_ctx():
    store.set_setting("custom_llm_base_url", "http://localhost:8080/v1")
    model = llm_providers.build_chat_model("custom", "some-model", "key")
    assert model.extra_body is None


def test_resolve_timeout_ollama_default_is_generous():
    # inferência sem GPU é lenta (ver docstring) — default bem maior que o
    # de um provider cloud.
    assert llm_providers._resolve_timeout("ollama", None) == llm_providers.DEFAULT_OLLAMA_TIMEOUT_SECONDS
    assert llm_providers._resolve_timeout("anthropic", None) == llm_providers.DEFAULT_TIMEOUT_SECONDS


def test_resolve_timeout_ollama_respects_configured_setting():
    store.set_setting("ollama_timeout_seconds", "45")
    assert llm_providers._resolve_timeout("ollama", None) == 45


def test_resolve_timeout_explicit_value_always_wins():
    store.set_setting("ollama_timeout_seconds", "45")
    assert llm_providers._resolve_timeout("ollama", 7) == 7


@pytest.mark.parametrize("raw,expected", [
    ("https://host.example.com", "https://host.example.com/v1"),
    ("https://host.example.com/", "https://host.example.com/v1"),
    ("https://host.example.com/v1", "https://host.example.com/v1"),
    ("https://host.example.com/v1/", "https://host.example.com/v1"),
])
def test_normalize_ollama_base_url(raw, expected):
    assert llm_providers._normalize_ollama_base_url(raw) == expected


def test_build_chat_model_ollama_normalizes_base_url_without_v1():
    # Mesma URL "pelada" que o phalanx aceita (LiteLLM/CrewAI fala com a API
    # nativa do Ollama) — o ChatOpenAI daqui precisa do /v1 explícito.
    store.set_setting("ollama_base_url", "https://ollama-remoto.example.com/")
    model = llm_providers.build_chat_model("ollama", "qwen2.5:14b", "token")
    assert model.openai_api_base == "https://ollama-remoto.example.com/v1"


def test_build_chat_model_custom_does_not_normalize_base_url():
    # "custom" pode ser qualquer endpoint compatível com OpenAI — não
    # assume convenção de path, ao contrário do Ollama.
    store.set_setting("custom_llm_base_url", "https://custom.example.com/api")
    model = llm_providers.build_chat_model("custom", "some-model", "key")
    assert model.openai_api_base == "https://custom.example.com/api"


@pytest.mark.parametrize("raw,expected", [
    ("qwen3-coder:30b", "qwen3-coder:30b"),
    ("ollama/qwen3-coder:30b", "qwen3-coder:30b"),
    ("ollama_chat/qwen3-coder:30b", "qwen3-coder:30b"),
])
def test_normalize_ollama_model(raw, expected):
    assert llm_providers._normalize_ollama_model(raw) == expected


def test_build_chat_model_ollama_strips_litellm_prefix_from_model_copied_from_phalanx():
    # phalanx (LiteLLM) usa "ollama/<modelo>" como convenção de roteamento;
    # o Argus fala direto com a API do Ollama, que só reconhece o nome puro
    # — colar o mesmo default_llm_model do phalanx sem isso dá "model not
    # found" no Ollama.
    store.set_setting("ollama_base_url", "http://localhost:11434")
    model = llm_providers.build_chat_model("ollama", "ollama/qwen3-coder:30b", "token")
    assert model.model_name == "qwen3-coder:30b"


def test_build_chat_model_custom_does_not_strip_model_prefix():
    store.set_setting("custom_llm_base_url", "http://localhost:8080/v1")
    model = llm_providers.build_chat_model("custom", "ollama/some-model", "key")
    assert model.model_name == "ollama/some-model"


def test_build_chat_model_ollama_uses_configured_timeout():
    store.set_setting("ollama_base_url", "http://localhost:11434/v1")
    store.set_setting("ollama_timeout_seconds", "600")
    model = llm_providers.build_chat_model("ollama", "qwen2.5:14b", "")
    assert model.request_timeout == 600
