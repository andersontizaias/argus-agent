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
    with pytest.raises(ValueError, match="Provider desconhecido"):
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
