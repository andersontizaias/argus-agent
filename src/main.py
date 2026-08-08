"""
Argus Agent — FastAPI Application
Agente de QA autônomo (web, Android, iOS) powered by LangGraph
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Mount

from src import (  # noqa: F401 — import ajusta PATH/env pro Android SDK (efeito colateral)
    android_env,
    store,
)
from src.auth import ApiKeyMiddleware
from src.mcp_server import mcp_server
from src.routers import api_keys as api_keys_router
from src.routers import config as config_router
from src.routers import health as health_router
from src.routers import runs as runs_router
from src.settings import HOST, PORT, VERSION

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

# A proteção a DNS rebinding do SDK do MCP nega TUDO por padrão
# (allowed_hosts/allowed_origins vazios) — sem isso, até o Claude Code
# rodando na mesma máquina toma 421 "Invalid Host header" (achado rodando
# de verdade). `HOST`/`PORT` cobrem o bind configurado; as variantes fixas
# cobrem o caso comum de rodar com o `.env` default sem PORT customizada.
_MCP_ALLOWED_HOSTS = [
    f"{HOST}:{PORT}", HOST, "127.0.0.1", f"127.0.0.1:{PORT}", "localhost", f"localhost:{PORT}",
]


def _build_mcp_asgi_app():
    """`streamable_http_path="/"` porque o Mount abaixo já prefixa com
    "/mcp" — sem isso o endpoint ficaria em "/mcp/mcp" (o default do
    próprio SDK é "/mcp"). Uma `StreamableHTTPSessionManager` só pode ser
    rodada UMA VEZ por instância (é recriada do zero a cada chamada de
    `streamable_http_app()`, achado rodando os testes: a segunda entrada
    no lifespan — outro `with TestClient(app)`, ou um reinício de verdade
    do processo — levantava "can only be called once per instance").
    Chamada de novo a cada entrada no lifespan (ver `lifespan` abaixo)."""
    sub_app = mcp_server.streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            allowed_hosts=_MCP_ALLOWED_HOSTS, allowed_origins=_MCP_ALLOWED_HOSTS
        ),
    )
    sub_app.add_middleware(ApiKeyMiddleware)
    return sub_app


# Registrado uma vez (o Mount precisa de um alvo estável pro `app.routes`
# desde o import), mas seu `.app` é trocado a cada entrada no lifespan pra
# apontar pro sub-app (e session manager) recém-criados.
_mcp_mount = Mount("/mcp", app=_build_mcp_asgi_app())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa o banco no startup (schema já deve existir via alembic em
    produção; create_all é idempotente e cobre dev/test sem depender de rodar
    a migração toda hora). O `session_manager` do MCP roda dentro do MESMO
    lifespan — um sub-app montado via `app.mount` não tem seu próprio
    lifespan invocado automaticamente pelo Starlette — e é reconstruído do
    zero a cada entrada (ver `_build_mcp_asgi_app`)."""
    store.init_db()
    _mcp_mount.app = _build_mcp_asgi_app()
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(
    title="Argus Agent",
    description="Agente de QA autônomo — web, Android e iOS",
    version=VERSION,
    lifespan=lifespan,
)

app.include_router(config_router.router)
app.include_router(health_router.router)
app.include_router(api_keys_router.router)
app.include_router(runs_router.router)
app.router.routes.append(_mcp_mount)

# ─── SPA (React, buildado via `npm run build` em frontend/) ───────
# Em dev, roda `npm run dev` em frontend/ (Vite dev server na :5173,
# proxy /api/* para este processo FastAPI — ver frontend/vite.config.ts).
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="spa-assets")
    if (FRONTEND_DIST / "img").exists():
        app.mount("/img", StaticFiles(directory=FRONTEND_DIST / "img"), name="spa-img")

    # Fallback via exception handler (404), NÃO uma rota catch-all
    # (`@app.get("/{full_path:path}")`) — um catch-all é uma ROTA de
    # verdade que participa do algoritmo de matching do Starlette: pra
    # qualquer caminho tipo "/mcp" (sem barra final) ela cria um match
    # PARCIAL (caminho bate, método GET não bate com POST), e um match
    # parcial impede o Starlette de tentar o redirect-with-trailing-slash
    # que o Mount do MCP precisa pra funcionar sem barra final — o
    # resultado observado ao vivo era 405 em vez do 307→200 esperado. Um
    # exception handler só entra em ação quando NENHUMA rota bateu (nem
    # parcialmente), então não interfere no matching de `/mcp`, `/assets`
    # nem `/img`.
    @app.exception_handler(404)
    async def serve_spa(_request: Request, _exc: Exception) -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")


def start():
    """CLI entrypoint."""
    import uvicorn
    uvicorn.run("src.main:app", host=HOST, port=PORT, reload=True)


if __name__ == "__main__":
    start()
