"""Argus Agent — autenticação por API key.

A UI não tem login (ferramenta local, single-user por design — ver
PLANO.md, decisão "Auth") — a barreira real é o bind em `127.0.0.1` por
padrão. Chamadas de fora (CI/CD, MCP, A2A) usam `X-API-Key`. Em bind
loopback, a chave só é exigida se `ARGUS_REQUIRE_API_KEY=1`; fora de
loopback é sempre exigida, para nunca aceitar tráfego externo sem auth."""
from fastapi import Header, HTTPException, status

from src import store
from src.settings import IS_LOOPBACK, REQUIRE_API_KEY


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if IS_LOOPBACK and not REQUIRE_API_KEY:
        return
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Header X-API-Key obrigatório.")
    if not store.verify_api_key(x_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-API-Key inválida ou revogada.")
