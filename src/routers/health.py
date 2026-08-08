"""Argus Agent — API: /api/health (doctor do ambiente, sem autenticação —
consumido pela UI para exibir os badges de ambiente)."""
import asyncio

from fastapi import APIRouter, Response

from src.doctor import run_checks
from src.settings import VERSION

router = APIRouter()


@router.get("/api/health")
async def health(response: Response):
    # run_checks() usa a API síncrona do Playwright, que se recusa a rodar
    # dentro de um event loop asyncio — to_thread executa numa thread real,
    # sem loop, satisfazendo essa checagem.
    checks = await asyncio.to_thread(run_checks)
    healthy = all(c.ok for c in checks)
    response.status_code = 200 if healthy else 503
    return {
        "status": "ok" if healthy else "degraded",
        "version": VERSION,
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks],
    }
