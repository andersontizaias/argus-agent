"""Argus Agent — API: configuração de providers LLM, secrets e settings.

Padrão de masking herdado do phalanx (src/routers/config.py de lá): o GET
nunca devolve o valor real de um secret, só um placeholder mascarado; o POST
reenviando esse placeholder preserva o valor já salvo em vez de sobrescrever
com lixo."""
import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src import store, user_secrets
from src.llm_providers import (
    SUPPORTED_PROVIDERS,
    build_chat_model,
    is_provider_configured,
)

router = APIRouter()


def _mask_secret(value: str) -> str:
    if not value:
        return value
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


def _preserve_masked(new_value: str, existing_value: str) -> str:
    """Se o campo voltou como veio (contém '****'), o usuário não mexeu nele —
    mantém o valor já salvo em vez de gravar o placeholder mascarado."""
    if not new_value or "****" in new_value:
        return existing_value
    return new_value


@router.get("/api/config")
async def get_config():
    secrets = {p.secret_name: _mask_secret(user_secrets.get_secret_plain(p.secret_name)) for p in SUPPORTED_PROVIDERS if p.needs_api_key}
    settings = {
        "ollama_base_url": store.get_setting("ollama_base_url"),
        "ollama_timeout_seconds": store.get_setting("ollama_timeout_seconds"),
        "custom_llm_base_url": store.get_setting("custom_llm_base_url"),
        "default_llm_provider": store.get_setting("default_llm_provider"),
        "default_llm_model": store.get_setting("default_llm_model"),
    }
    return {**secrets, **settings}


class ConfigUpdate(BaseModel):
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    ollama_api_key: str = ""
    ollama_base_url: str = ""
    ollama_timeout_seconds: str = ""
    custom_llm_api_key: str = ""
    custom_llm_base_url: str = ""
    default_llm_provider: str = ""
    default_llm_model: str = ""


@router.post("/api/config")
async def save_config(update: ConfigUpdate):
    if update.ollama_timeout_seconds and not update.ollama_timeout_seconds.isdigit():
        return JSONResponse(status_code=400, content={"error": "Timeout do Ollama precisa ser um número inteiro de segundos."})

    for provider in SUPPORTED_PROVIDERS:
        if not provider.needs_api_key:
            continue
        new_value = getattr(update, provider.secret_name, "")
        existing = user_secrets.get_secret_plain(provider.secret_name)
        user_secrets.set_secret_plain(provider.secret_name, _preserve_masked(new_value, existing))

    store.set_setting("ollama_base_url", update.ollama_base_url)
    store.set_setting("ollama_timeout_seconds", update.ollama_timeout_seconds)
    store.set_setting("custom_llm_base_url", update.custom_llm_base_url)
    store.set_setting("default_llm_provider", update.default_llm_provider)
    store.set_setting("default_llm_model", update.default_llm_model)
    return {"status": "ok", "message": "Configuração salva com sucesso."}


@router.post("/api/config/test-llm-provider/{provider_id}")
async def test_llm_provider(provider_id: str):
    """Faz uma chamada real e mínima ao provider configurado — sucesso aqui é
    garantia de que as credenciais funcionam para uma run de verdade (mesmo
    padrão do test-llm-provider do phalanx)."""
    provider = next((p for p in SUPPORTED_PROVIDERS if p.id == provider_id), None)
    if not provider:
        return JSONResponse(status_code=404, content={"error": "Provider desconhecido."})

    if not is_provider_configured(provider_id):
        return JSONResponse(status_code=400, content={"error": f"{provider.label} não está configurado."})

    try:
        api_key = user_secrets.get_secret_plain(provider.secret_name)
        model = build_chat_model(provider_id, provider.example_model, api_key, max_tokens=5, timeout=15)
        # .invoke é síncrono — rodar direto travaria o event loop inteiro
        # (outras requisições) até o provider responder, especialmente ruim
        # pra um Ollama remoto/lento (ver DEFAULT_OLLAMA_TIMEOUT_SECONDS).
        await asyncio.to_thread(model.invoke, "Reply with only the single word: pong")
        return {"ok": True, "provider": provider_id, "model": provider.example_model}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Falha na conexão: {e!s}"})
