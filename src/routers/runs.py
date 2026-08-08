"""Argus Agent — API REST de runs: criar, listar, acompanhar (SSE), cancelar,
baixar relatório/evidências. É a superfície que CI/CD e integrações usam
(`X-API-Key` — ver src/auth.py); a UI web fala com os mesmos endpoints, sem
precisar da chave enquanto o servidor estiver em bind loopback."""
import asyncio
import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from src import auth, models, store
from src.bdd import BddParseError, parse_bdd_script, validate_test_data
from src.events import list_events
from src.llm_providers import get_provider

router = APIRouter(dependencies=[Depends(auth.require_api_key)])

TERMINAL_STATUSES = {"passed", "failed", "error", "canceled"}
_VALID_PLATFORMS = {"web", "android", "ios"}


class RunCreate(BaseModel):
    platform: str
    app_url: str | None = None
    binary_url: str | None = None
    binary_auth_secret: str | None = None
    bdd_script: str
    test_data: dict[str, str] = {}
    llm_provider: str | None = None
    llm_model: str | None = None


def _scenario_dict(scenario: models.Scenario) -> dict:
    steps = store.list_steps(scenario.id)
    return {
        "id": scenario.id,
        "position": scenario.position,
        "name": scenario.name,
        "tags": scenario.tags.split(",") if scenario.tags else [],
        "status": scenario.status,
        "failure_reason": scenario.failure_reason,
        "started_at": scenario.started_at.isoformat() if scenario.started_at else None,
        "finished_at": scenario.finished_at.isoformat() if scenario.finished_at else None,
        "steps": [_step_dict(step) for step in steps],
    }


def _step_dict(step: models.Step) -> dict:
    evidences = store.list_evidences_by_step(step.id)
    return {
        "id": step.id,
        "position": step.position,
        "keyword": step.keyword,
        "text": step.text,
        "status": step.status,
        "error": step.error,
        "attempts": step.attempts,
        "duration_ms": step.duration_ms,
        "evidences": [{"id": e.id, "type": e.type, "label": e.label} for e in evidences],
    }


def _run_detail_dict(run: models.Run) -> dict:
    return {
        **_run_summary_dict(run),
        "bdd_script": run.bdd_script,
        "test_data_keys": sorted(store.get_run_test_data(run.id).keys()),
        "scenarios": [_scenario_dict(s) for s in store.list_scenarios(run.id)],
    }


def _run_summary_dict(run: models.Run) -> dict:
    return {
        "id": run.id,
        "platform": run.platform,
        "app_url": run.app_url,
        "binary_url": run.binary_url,
        "status": run.status,
        "error": run.error,
        "cancel_requested": run.cancel_requested,
        "llm_provider": run.llm_provider,
        "llm_model": run.llm_model,
        "scenarios_total": run.scenarios_total,
        "scenarios_passed": run.scenarios_passed,
        "scenarios_failed": run.scenarios_failed,
        "tokens_in": run.tokens_in,
        "tokens_out": run.tokens_out,
        "cost_usd": run.cost_usd,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.post("/api/runs")
async def create_run(payload: RunCreate):
    if payload.platform not in _VALID_PLATFORMS:
        return JSONResponse(status_code=400, content={"error": f"Plataforma inválida: {payload.platform}"})
    if payload.platform != "web" and not payload.binary_url:
        return JSONResponse(status_code=400, content={"error": f"Plataforma '{payload.platform}' exige binary_url."})
    if not payload.bdd_script.strip():
        return JSONResponse(status_code=400, content={"error": "Script BDD vazio."})

    try:
        scenarios = parse_bdd_script(payload.bdd_script)
        validate_test_data(scenarios, payload.test_data)
    except BddParseError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    llm_provider = payload.llm_provider or store.get_setting("default_llm_provider")
    llm_model = payload.llm_model or store.get_setting("default_llm_model")
    if not llm_provider or not get_provider(llm_provider):
        return JSONResponse(status_code=400, content={"error": "Nenhum provider LLM configurado (defina um default em /config ou informe llm_provider)."})

    run = store.create_run(
        platform=payload.platform,
        app_url=payload.app_url,
        binary_url=payload.binary_url,
        binary_auth_secret=payload.binary_auth_secret,
        bdd_script=payload.bdd_script,
        test_data=payload.test_data,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    return _run_summary_dict(run)


@router.get("/api/runs")
async def list_runs(limit: int = 20, offset: int = 0, status: str | None = None, platform: str | None = None):
    limit = max(1, min(limit, 100))
    runs = store.list_runs(limit=limit, offset=offset, status=status, platform=platform)
    total = store.count_runs(status=status, platform=platform)
    return {"runs": [_run_summary_dict(r) for r in runs], "total": total, "limit": limit, "offset": offset}


@router.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = store.get_run(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "Run não encontrada."})
    return _run_detail_dict(run)


@router.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    run = store.get_run(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "Run não encontrada."})
    if run.status in TERMINAL_STATUSES:
        return JSONResponse(status_code=400, content={"error": f"Run já terminou (status: {run.status})."})
    store.request_cancel(run_id)
    return {"id": run_id, "cancel_requested": True}


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


@router.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request, after: int = 0):
    run = store.get_run(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "Run não encontrada."})

    async def event_generator():
        last_seq = after
        current = store.get_run(run_id)
        if current:
            yield _sse("run_snapshot", _run_detail_dict(current))
        idle_ticks = 0
        while not await request.is_disconnected():
            new_events = list_events(run_id, after_seq=last_seq)
            for ev in new_events:
                last_seq = ev.id
                yield _sse(ev.type, {"seq": ev.id, **ev.payload})
            current = store.get_run(run_id)
            if current and current.status in TERMINAL_STATUSES and not new_events:
                yield _sse("run_snapshot", _run_detail_dict(current))
                break
            if new_events:
                idle_ticks = 0
                continue
            idle_ticks += 1
            if idle_ticks % 30 == 0:  # ~15s (0.5s * 30) sem eventos novos
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/runs/{run_id}/report")
async def get_report(run_id: str):
    run = store.get_run(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "Run não encontrada."})
    if not run.artifacts_dir:
        return JSONResponse(status_code=404, content={"error": "Relatório ainda não disponível — a run não terminou."})
    report_path = Path(run.artifacts_dir) / "report.json"
    if not report_path.exists():
        return JSONResponse(status_code=404, content={"error": "report.json não encontrado."})
    return JSONResponse(content=json.loads(report_path.read_text(encoding="utf-8")))


@router.get("/api/runs/{run_id}/report.html")
async def get_report_html(run_id: str):
    run = store.get_run(run_id)
    if not run or not run.artifacts_dir:
        return JSONResponse(status_code=404, content={"error": "Relatório ainda não disponível."})
    report_path = Path(run.artifacts_dir) / "report.html"
    if not report_path.exists():
        return JSONResponse(status_code=404, content={"error": "report.html não encontrado."})
    return FileResponse(report_path, media_type="text/html")


@router.get("/api/runs/{run_id}/artifacts.zip")
async def get_artifacts_zip(run_id: str):
    run = store.get_run(run_id)
    if not run or not run.artifacts_dir:
        return JSONResponse(status_code=404, content={"error": "Artefatos ainda não disponíveis."})
    artifacts_dir = Path(run.artifacts_dir)
    if not artifacts_dir.exists():
        return JSONResponse(status_code=404, content={"error": "Diretório de artefatos não encontrado."})

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in artifacts_dir.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(artifacts_dir))
    buffer.seek(0)
    return Response(
        content=buffer.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="argus-run-{run_id}.zip"'},
    )


@router.get("/api/evidences/{evidence_id}")
async def get_evidence(evidence_id: str):
    evidence = store.get_evidence(evidence_id)
    if not evidence:
        return JSONResponse(status_code=404, content={"error": "Evidência não encontrada."})
    path = Path(evidence.path)
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "Arquivo da evidência não encontrado em disco."})
    return FileResponse(path)
