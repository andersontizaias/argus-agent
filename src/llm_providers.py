"""Argus Agent — registro de providers LLM.

Cada provider mapeia para um modelo LangChain via `init_chat_model` (rota
oficial multi-provider do LangChain). "ollama" e "custom" reaproveitam o
`ChatOpenAI` apontando para um `base_url` compatível com a API da OpenAI —
mesma convenção do `custom/<model>` do phalanx, sem precisar de um pacote
dedicado por host self-hosted.
"""
from dataclasses import dataclass

from src import store


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    needs_api_key: bool
    needs_base_url: bool
    example_model: str  # sem o prefixo do provider — só o nome do modelo
    secret_name: str  # nome da linha em `secrets` (chave cifrada)


SUPPORTED_PROVIDERS = [
    ProviderInfo("anthropic", "Anthropic", needs_api_key=True, needs_base_url=False,
                 example_model="claude-3-5-haiku-latest", secret_name="anthropic_api_key"),
    ProviderInfo("openai", "OpenAI", needs_api_key=True, needs_base_url=False,
                 example_model="gpt-4o-mini", secret_name="openai_api_key"),
    ProviderInfo("google_genai", "Google Gemini", needs_api_key=True, needs_base_url=False,
                 example_model="gemini-2.5-flash", secret_name="gemini_api_key"),
    ProviderInfo("groq", "Groq", needs_api_key=True, needs_base_url=False,
                 example_model="llama-3.3-70b-versatile", secret_name="groq_api_key"),
    ProviderInfo("ollama", "Ollama (local)", needs_api_key=False, needs_base_url=True,
                 example_model="qwen2.5:14b", secret_name="ollama_api_key"),
    ProviderInfo("custom", "Custom (endpoint compatível com OpenAI)", needs_api_key=True, needs_base_url=True,
                 example_model="", secret_name="custom_llm_api_key"),
]

_BASE_URL_SETTING_KEYS = {
    "ollama": "ollama_base_url",
    "custom": "custom_llm_base_url",
}


def get_provider(provider_id: str) -> ProviderInfo | None:
    return next((p for p in SUPPORTED_PROVIDERS if p.id == provider_id), None)


def is_provider_configured(provider_id: str) -> bool:
    provider = get_provider(provider_id)
    if not provider:
        return False
    if provider.needs_api_key and not store.get_secret(provider.secret_name):
        return False
    return not (provider.needs_base_url and not store.get_setting(_BASE_URL_SETTING_KEYS[provider.id]))


def build_chat_model(provider_id: str, model: str, api_key_plain: str, *, max_tokens: int = 1024, timeout: int = 30):
    """Constrói um chat model LangChain pronto para uso. `api_key_plain` já vem
    decifrado pelo caller (src/user_secrets.py) — este módulo nunca lê o banco
    diretamente para não acoplar a camada de LLM à de persistência."""
    provider = get_provider(provider_id)
    if not provider:
        raise ValueError(f"Provider desconhecido: {provider_id}")

    if provider.id in ("ollama", "custom"):
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr

        base_url = store.get_setting(_BASE_URL_SETTING_KEYS[provider.id])
        if not base_url:
            raise ValueError(f"{provider.label} precisa de uma base URL configurada.")
        return ChatOpenAI(
            model=model,
            api_key=SecretStr(api_key_plain or "ollama"),  # Ollama ignora o valor, mas o cliente exige algo não-vazio
            base_url=base_url,
            max_completion_tokens=max_tokens,
            timeout=timeout,
        )

    from langchain.chat_models import init_chat_model

    return init_chat_model(
        model=model,
        model_provider=provider.id,
        api_key=api_key_plain,
        max_tokens=max_tokens,
        timeout=timeout,
    )
