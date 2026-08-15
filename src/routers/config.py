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
    default_model_setting_name,
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


def _set_setting_if_provided(key: str, value: str | None) -> None:
    """`None` = o campo não veio no corpo do POST — não mexe no setting já
    salvo. `""` continua um valor válido e intencional (ver comentário em
    `ConfigUpdate`) — só a ausência do campo é ignorada."""
    if value is not None:
        store.set_setting(key, value)


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
        "retention_days": store.get_setting("retention_days") or str(prune.DEFAULT_RETENTION_DAYS),
    }
    # Modelo default é um setting POR provider (não um único global) — cada
    # provider configurado guarda o seu preferido, ao lado da chave/URL dele
    # na UI, em vez de uma seção separada desacoplada de qual provider é.
    settings.update({default_model_setting_name(p): store.get_setting(default_model_setting_name(p)) for p in SUPPORTED_PROVIDERS})
    return {**secrets, **settings}


class ConfigUpdate(BaseModel):
    # Secrets: sempre `str = ""` — a ausência de "clientes parciais" pra
    # secrets não importa aqui porque `_preserve_masked` já trata "" (e o
    # placeholder mascarado) como "não mexeu, preserva o que já tem".
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    ollama_api_key: str = ""
    custom_llm_api_key: str = ""
    bedrock_api_key: str = ""
    bedrock_access_key_id: str = ""
    bedrock_secret_access_key: str = ""
    bedrock_session_token: str = ""

    # Settings: `str | None = None` (campo OMITIDO no JSON vira None) em vez
    # de `str = ""` — sem isso, um POST parcial (qualquer caller que não seja
    # a própria UI, que sempre reenvia o estado inteiro da tela) reseta pra
    # vazio todo campo que não mandou, silenciosamente. `""` continua um
    # valor válido e intencional (ex.: limpar "Provider default" via
    # "Nenhum" na UI) — só a ausência do campo é ignorada, nunca o valor
    # vazio explícito. Visto ao vivo: um POST com corpo `{}` apagou
    # ollama_base_url/bedrock_region/default_llm_provider de uma instância
    # real.
    ollama_base_url: str | None = None
    ollama_timeout_seconds: str | None = None
    custom_llm_base_url: str | None = None
    bedrock_region: str | None = None
    default_llm_provider: str | None = None
    anthropic_default_model: str | None = None
    openai_default_model: str | None = None
    gemini_default_model: str | None = None
    groq_default_model: str | None = None
    ollama_default_model: str | None = None
    custom_llm_default_model: str | None = None
    bedrock_default_model: str | None = None
    retention_days: str | None = None


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

    _set_setting_if_provided("ollama_base_url", update.ollama_base_url)
    _set_setting_if_provided("ollama_timeout_seconds", update.ollama_timeout_seconds)
    _set_setting_if_provided("custom_llm_base_url", update.custom_llm_base_url)
    _set_setting_if_provided("bedrock_region", update.bedrock_region)
    _set_setting_if_provided("default_llm_provider", update.default_llm_provider)
    for provider in SUPPORTED_PROVIDERS:
        key = default_model_setting_name(provider)
        _set_setting_if_provided(key, getattr(update, key, None))
    _set_setting_if_provided("retention_days", update.retention_days)
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

    # Cada provider guarda seu próprio modelo default (não só o "provider
    # default" global) — testa com ele quando existir. Importa
    # especialmente pro Ollama: só funciona se o modelo já tiver sido
    # baixado NAQUELE servidor, então o `example_model` hardcoded pode nunca
    # ter sido `ollama pull`ado lá.
    test_model = store.get_setting(default_model_setting_name(provider)) or provider.example_model

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
