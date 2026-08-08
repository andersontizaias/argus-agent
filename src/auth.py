"""Argus Agent — autenticação por API key.

A UI não tem login (ferramenta local, single-user por design — ver
PLANO.md, decisão "Auth") — a barreira real é o bind em `127.0.0.1` por
padrão. Chamadas de fora (CI/CD, MCP, A2A) usam `X-API-Key`. Em bind
loopback, a chave só é exigida se `ARGUS_REQUIRE_API_KEY=1`; fora de
loopback é sempre exigida, para nunca aceitar tráfego externo sem auth."""
from fastapi import Header, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src import store
from src.settings import IS_LOOPBACK, REQUIRE_API_KEY


def is_authorized(x_api_key: str | None) -> bool:
    """Regra pura (sem depender do FastAPI) — reusada tanto pela `Depends()`
    abaixo quanto por `ApiKeyMiddleware`, usado pelo sub-app do MCP (que é
    Starlette puro, montado via `app.mount`, e não passa pelas `Depends()`
    do app FastAPI principal)."""
    if IS_LOOPBACK and not REQUIRE_API_KEY:
        return True
    if not x_api_key:
        return False
    return store.verify_api_key(x_api_key) is not None


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if is_authorized(x_api_key):
        return
    detail = "Header X-API-Key obrigatório." if not x_api_key else "X-API-Key inválida ou revogada."
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Mesma regra de `require_api_key`, em forma de middleware ASGI puro."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not is_authorized(request.headers.get("x-api-key")):
            return JSONResponse({"error": "X-API-Key obrigatória ou inválida."}, status_code=401)
        return await call_next(request)
