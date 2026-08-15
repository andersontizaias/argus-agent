"""Argus Agent — API: configuração de providers LLM, secrets e settings.

Padrão de masking herdado do phalanx (src/routers/config.py de lá): o GET
nunca devolve o valor real de um secret, só um placeholder mascarado; o POST
reenviando esse placeholder preserva o valor já salvo em vez de sobrescrever
com lixo."""
import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src import auth, prune, store, user_secrets
from src.llm_providers import (
    SUPPORTED_PROVIDERS,
    build_chat_model,
    is_provider_configured,
)

router = APIRouter(dependencies=[Depends(auth.require_api_key)])


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


_BEDROCK_ADVANCED_SECRET_NAMES = ("bedrock_access_key_id", "bedrock_secret_access_key", "bedrock_session_token")


@router.get("/api/config")
async def get_config():
    # Não filtra por `needs_api_key`: esse flag é sobre o provider EXIGIR
    # chave pra funcionar (ex.: Anthropic sim, Ollama não) — não sobre se o
    # campo existe. Ollama/custom aceitam uma chave opcional (Bearer token
    # de um reverse proxy na frente do servidor), e um `if p.needs_api_key`
    # aqui os excluía silenciosamente da resposta.
    secrets = {p.secret_name: _mask_secret(user_secrets.get_secret_plain(p.secret_name)) for p in SUPPORTED_PROVIDERS}
    # Bedrock tem 3 secrets extras (modo avançado, SigV4) que não são
    # `secret_name` de nenhum provider — o loop acima não os cobre.
    secrets.update({name: _mask_secret(user_secrets.get_secret_plain(name)) for name in _BEDROCK_ADVANCED_SECRET_NAMES})
    settings = {
        "ollama_base_url": store.get_setting("ollama_base_url"),
        "ollama_timeout_seconds": store.get_setting("ollama_timeout_seconds"),
        "custom_llm_base_url": store.get_setting("custom_llm_base_url"),
        "bedrock_region": store.get_setting("bedrock_region"),
        "default_llm_provider": store.get_setting("default_llm_provider"),
        "default_llm_model": store.get_setting("default_llm_model"),
        "retention_days": store.get_setting("retention_days") or str(prune.DEFAULT_RETENTION_DAYS),
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
    bedrock_api_key: str = ""
    bedrock_access_key_id: str = ""
    bedrock_secret_access_key: str = ""
    bedrock_session_token: str = ""
    bedrock_region: str = ""
    default_llm_provider: str = ""
    default_llm_model: str = ""
    retention_days: str = ""


@router.post("/api/config")
async def save_config(update: ConfigUpdate):
    if update.ollama_timeout_seconds and not update.ollama_timeout_seconds.isdigit():
        return JSONResponse(status_code=400, content={"error": "Ollama timeout must be a whole number of seconds."})
    if update.retention_days and not update.retention_days.isdigit():
        return JSONResponse(status_code=400, content={"error": "Retention must be a whole number of days (0 disables pruning)."})

    # Mesmo raciocínio do get_config acima: salva a chave de todo provider,
    # exigida ou não — o bug original (`if not provider.needs_api_key:
    # continue`) descartava silenciosamente a chave do Ollama/custom no
    # POST, então preenchê-la na UI nunca persistia nada.
    for provider in SUPPORTED_PROVIDERS:
        new_value = getattr(update, provider.secret_name, "")
        existing = user_secrets.get_secret_plain(provider.secret_name)
        user_secrets.set_secret_plain(provider.secret_name, _preserve_masked(new_value, existing))

    # Mesmo tratamento pros 3 secrets avançados do Bedrock (fora do loop
    # genérico acima — nenhum é `secret_name` de provider nenhum).
    for name in _BEDROCK_ADVANCED_SECRET_NAMES:
        new_value = getattr(update, name, "")
        existing = user_secrets.get_secret_plain(name)
        user_secrets.set_secret_plain(name, _preserve_masked(new_value, existing))

    store.set_setting("ollama_base_url", update.ollama_base_url)
    store.set_setting("ollama_timeout_seconds", update.ollama_timeout_seconds)
    store.set_setting("custom_llm_base_url", update.custom_llm_base_url)
    store.set_setting("bedrock_region", update.bedrock_region)
    store.set_setting("default_llm_provider", update.default_llm_provider)
    store.set_setting("default_llm_model", update.default_llm_model)
    store.set_setting("retention_days", update.retention_days)
    return {"status": "ok", "message": "Configuração salva com sucesso."}


@router.post("/api/config/test-llm-provider/{provider_id}")
async def test_llm_provider(provider_id: str):
    """Faz uma chamada real e mínima ao provider configurado — sucesso aqui é
    garantia de que as credenciais funcionam para uma run de verdade (mesmo
    padrão do test-llm-provider do phalanx)."""
    provider = next((p for p in SUPPORTED_PROVIDERS if p.id == provider_id), None)
    if not provider:
        return JSONResponse(status_code=404, content={"error": "Unknown provider."})

    if not is_provider_configured(provider_id):
        return JSONResponse(status_code=400, content={"error": f"{provider.label} isn't configured."})

    # Provider cloud: qualquer example_model fixo sempre existe do lado do
    # provider. Ollama é diferente — só funciona se o modelo já tiver sido
    # baixado NAQUELE servidor — então testa com o modelo default que o
    # usuário configurou pra esse provider (quando houver um), não um nome
    # hardcoded que pode nunca ter sido `ollama pull`ado lá.
    test_model = provider.example_model
    if store.get_setting("default_llm_provider") == provider_id:
        test_model = store.get_setting("default_llm_model") or test_model

    # Providers cloud: 15s é de sobra pra um "pong" de 5 tokens — falha
    # rápido se a credencial estiver errada. Ollama é o oposto: mesmo com
    # tudo certo, a primeira chamada pode incluir carregar o modelo na
    # memória do servidor (cold start), que sozinho já pode passar de 15s
    # numa máquina sem GPU — usa o mesmo timeout configurável de uma
    # chamada real (ollama_timeout_seconds) em vez de um valor fixo curto.
    test_timeout = None if provider.id == "ollama" else 15

    try:
        api_key = user_secrets.get_secret_plain(provider.secret_name)
        # Bedrock tem um modo avançado (SigV4) além da API key — mesma
        # lógica do call site em src/agent/nodes.py.
        extra_credentials = user_secrets.get_bedrock_sigv4_credentials() if provider.id == "bedrock" else user_secrets.NO_EXTRA_CREDENTIALS
        model = build_chat_model(provider_id, test_model, api_key, max_tokens=5, timeout=test_timeout, **extra_credentials)
        # .invoke é síncrono — rodar direto travaria o event loop inteiro
        # (outras requisições) até o provider responder, especialmente ruim
        # pra um Ollama remoto/lento (ver DEFAULT_OLLAMA_TIMEOUT_SECONDS).
        await asyncio.to_thread(model.invoke, "Reply with only the single word: pong")
        return {"ok": True, "provider": provider_id, "model": test_model}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Connection failed: {e!s}"})
