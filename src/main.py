"""
Argus Agent — FastAPI Application
Agente de QA autônomo (web, Android, iOS) powered by LangGraph
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src import store
from src.routers import api_keys as api_keys_router
from src.routers import config as config_router
from src.routers import health as health_router
from src.routers import runs as runs_router
from src.settings import HOST, PORT

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa o banco no startup (schema já deve existir via alembic em
    produção; create_all é idempotente e cobre dev/test sem depender de rodar
    a migração toda hora)."""
    store.init_db()
    yield


app = FastAPI(
    title="Argus Agent",
    description="Agente de QA autônomo — web, Android e iOS",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(config_router.router)
app.include_router(health_router.router)
app.include_router(api_keys_router.router)
app.include_router(runs_router.router)

# ─── SPA (React, buildado via `npm run build` em frontend/) ───────
# Em dev, roda `npm run dev` em frontend/ (Vite dev server na :5173,
# proxy /api/* para este processo FastAPI — ver frontend/vite.config.ts).
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="spa-assets")
    if (FRONTEND_DIST / "img").exists():
        app.mount("/img", StaticFiles(directory=FRONTEND_DIST / "img"), name="spa-img")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        return FileResponse(FRONTEND_DIST / "index.html")


def start():
    """CLI entrypoint."""
    import uvicorn
    uvicorn.run("src.main:app", host=HOST, port=PORT, reload=True)


if __name__ == "__main__":
    start()
