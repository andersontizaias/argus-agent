"""Argus Agent — registro de providers LLM.

Cada provider mapeia para um modelo LangChain via `init_chat_model` (rota
oficial multi-provider do LangChain). "ollama" e "custom" reaproveitam o
`ChatOpenAI` apontando para um `base_url` compatível com a API da OpenAI —
mesma convenção do `custom/<model>` do phalanx, sem precisar de um pacote
dedicado por host self-hosted. O `base_url` do Ollama não precisa ser
localhost: `http://<host-remoto>:11434/v1` funciona igual (mesmo padrão do
phalanx — servidor Ollama rodando em outra máquina/VPS), inclusive atrás de
um reverse proxy com Bearer token (`ollama_api_key`, opcional).

"bedrock" aceita DOIS modos de autenticação, mutuamente exclusivos — a API
key (bearer token, curta OU longa duração) tem precedência quando presente:
1. `bedrock_api_key` — o caminho padrão. Um único token (o "Bedrock API key"
   da AWS), que pode expirar (sessão) ou não (atrelado a um IAM user).
   `ChatBedrockConverse` já injeta esse token num provider de credenciais
   estático por client (não por env var global `AWS_BEARER_TOKEN_BEDROCK`) —
   seguro pra um servidor concorrente com múltiplos tenants/providers.
2. Trio SigV4 clássico (`bedrock_access_key_id`/`bedrock_secret_access_key`/
   `bedrock_session_token`, o último opcional) — modo "avançado" pra quem
   prefere credenciais IAM tradicionais em vez da API key.
"""
from dataclasses import dataclass

from src import store

# Ollama zera o context window em 2048 tokens por padrão quando o caller não
# manda `num_ctx` — pouco pra um prompt com persona + snapshot da página +
# histórico do cenário, que trunca silenciosamente e degrada a qualidade das
# respostas. Mesmo ajuste (e mesmo valor) do phalanx (src/llm_providers.py
# de lá, OLLAMA_NUM_CTX) — reaproveitado aqui porque o sintoma é idêntico.
OLLAMA_NUM_CTX = 32768

# Inferência local/remota sem GPU é lenta (medido: ~2,5 tok/s — ver memória
# "Performance de inferência: gargalo é CPU sem GPU") — um timeout de
# provider cloud (dezenas de segundos) derruba toda chamada real ao Ollama
# antes da resposta terminar. Configurável via Config (ollama_timeout_seconds)
# para quem tiver GPU e quiser um timeout mais curto.
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 300


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
    ProviderInfo("ollama", "Ollama (local ou remoto)", needs_api_key=False, needs_base_url=True,
                 example_model="qwen2.5:14b", secret_name="ollama_api_key"),
    ProviderInfo("custom", "Custom (endpoint compatível com OpenAI)", needs_api_key=True, needs_base_url=True,
                 example_model="", secret_name="custom_llm_api_key"),
    # needs_api_key=False: a API key sozinha não é obrigatória — pode ser
    # substituída pelo trio SigV4 avançado (ver docstring do módulo). A
    # validação real ("algum dos dois modos está presente") é um special
    # case em `is_provider_configured`, não esse flag genérico.
    # example_model já com o prefixo de inference profile ("us.") — a
    # maioria dos modelos novos no Bedrock exige isso pra invocação
    # on-demand (mesmo espírito do strip de prefixo do Ollama, mas ao
    # contrário: aqui o prefixo É necessário).
    ProviderInfo("bedrock", "AWS Bedrock", needs_api_key=False, needs_base_url=True,
                 example_model="us.anthropic.claude-3-5-haiku-20241022-v1:0", secret_name="bedrock_api_key"),
]

_BASE_URL_SETTING_KEYS = {
    "ollama": "ollama_base_url",
    "custom": "custom_llm_base_url",
    "bedrock": "bedrock_region",
}


def get_provider(provider_id: str) -> ProviderInfo | None:
    return next((p for p in SUPPORTED_PROVIDERS if p.id == provider_id), None)


def is_provider_configured(provider_id: str) -> bool:
    provider = get_provider(provider_id)
    if not provider:
        return False
    if provider.id == "bedrock":
        # OR entre os dois modos de auth (ver docstring do módulo) — nem
        # `needs_api_key` nem o check genérico abaixo modelam isso.
        if not store.get_setting(_BASE_URL_SETTING_KEYS["bedrock"]):
            return False
        has_api_key = bool(store.get_secret("bedrock_api_key"))
        has_sigv4 = bool(store.get_secret("bedrock_access_key_id")) and bool(store.get_secret("bedrock_secret_access_key"))
        return has_api_key or has_sigv4
    if provider.needs_api_key and not store.get_secret(provider.secret_name):
        return False
    return not (provider.needs_base_url and not store.get_setting(_BASE_URL_SETTING_KEYS[provider.id]))


def _resolve_timeout(provider_id: str, timeout: int | None) -> int:
    """`timeout=None` (não passado pelo caller) escolhe um default por
    provider; um valor explícito (ex.: o ping curto de "testar provider")
    sempre prevalece."""
    if timeout is not None:
        return timeout
    if provider_id == "ollama":
        configured = store.get_setting("ollama_timeout_seconds")
        return int(configured) if configured else DEFAULT_OLLAMA_TIMEOUT_SECONDS
    return DEFAULT_TIMEOUT_SECONDS


def _normalize_ollama_base_url(base_url: str) -> str:
    """`ChatOpenAI` (SDK da OpenAI) monta a URL final como `base_url +
    "/chat/completions"`, sem assumir `/v1` sozinho — diferente do LiteLLM/
    CrewAI (usado no phalanx), que fala com a API nativa do Ollama e aceita
    a base URL "pelada" (ex.: `https://host/`). Sem essa normalização, a
    MESMA URL que funciona no phalanx dá 404 aqui. Aceita com ou sem barra
    final, com ou sem `/v1` já incluso."""
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1"):
        return base_url
    return f"{base_url}/v1"


# Prefixos de roteamento do LiteLLM (usados no phalanx, ex.:
# "ollama/qwen3-coder:30b") — não fazem sentido aqui: falamos direto com a
# API do Ollama (via ChatOpenAI), que só reconhece o nome puro do modelo
# ("qwen3-coder:30b"). Um usuário copiando o `default_llm_model` de lá pra
# cá recebe "model not found" sem esse strip.
_OLLAMA_LITELLM_PREFIXES = ("ollama_chat/", "ollama/")


def _normalize_ollama_model(model: str) -> str:
    for prefix in _OLLAMA_LITELLM_PREFIXES:
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


def build_chat_model(
    provider_id: str, model: str, api_key_plain: str, *, max_tokens: int = 1024, timeout: int | None = None,
    aws_access_key_id: str = "", aws_secret_access_key: str = "", aws_session_token: str = "",
):
    """Constrói um chat model LangChain pronto para uso. `api_key_plain` já vem
    decifrado pelo caller (src/user_secrets.py) — este módulo nunca lê o banco
    diretamente para não acoplar a camada de LLM à de persistência. Os 3 kwargs
    `aws_*` só são usados pelo modo avançado (SigV4) do Bedrock — todo outro
    provider os ignora."""
    provider = get_provider(provider_id)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_id}")

    resolved_timeout = _resolve_timeout(provider.id, timeout)

    if provider.id == "bedrock":
        from langchain_aws import ChatBedrockConverse
        from pydantic import SecretStr

        region = store.get_setting(_BASE_URL_SETTING_KEYS["bedrock"])
        if not region:
            raise ValueError(f"{provider.label} needs a configured AWS region.")
        if not api_key_plain and not (aws_access_key_id and aws_secret_access_key):
            raise ValueError(f"{provider.label} needs either an API key or an AWS access key/secret pair.")

        # ChatBedrockConverse já resolve api_key vs. credenciais AWS
        # internamente (injeta um token provider estático por client quando
        # a API key vem preenchida — ver langchain_aws.utils.create_aws_client)
        # — não precisa de nenhuma construção manual de client boto3/botocore
        # aqui. `api_key` é o nome real do kwarg — `bedrock_api_key` é só o
        # nome do field Python (alias="api_key").
        return ChatBedrockConverse(
            model=model,
            region_name=region,
            api_key=SecretStr(api_key_plain) if api_key_plain else None,
            aws_access_key_id=SecretStr(aws_access_key_id) if aws_access_key_id else None,
            aws_secret_access_key=SecretStr(aws_secret_access_key) if aws_secret_access_key else None,
            aws_session_token=SecretStr(aws_session_token) if aws_session_token else None,
            max_tokens=max_tokens,
            timeout=resolved_timeout,
        )

    if provider.id in ("ollama", "custom"):
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr

        base_url = store.get_setting(_BASE_URL_SETTING_KEYS[provider.id])
        if not base_url:
            raise ValueError(f"{provider.label} needs a configured base URL.")
        if provider.id == "ollama":
            base_url = _normalize_ollama_base_url(base_url)
            model = _normalize_ollama_model(model)
        extra_body = {"options": {"num_ctx": OLLAMA_NUM_CTX}} if provider.id == "ollama" else None
        return ChatOpenAI(
            model=model,
            api_key=SecretStr(api_key_plain or "ollama"),  # Ollama ignora o valor, mas o cliente exige algo não-vazio
            base_url=base_url,
            max_completion_tokens=max_tokens,
            timeout=resolved_timeout,
            extra_body=extra_body,
        )

    from langchain.chat_models import init_chat_model

    return init_chat_model(
        model=model,
        model_provider=provider.id,
        api_key=api_key_plain,
        max_tokens=max_tokens,
        timeout=resolved_timeout,
    )
