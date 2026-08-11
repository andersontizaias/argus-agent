"""Argus Agent — API REST de runs: criar, listar, acompanhar (SSE), cancelar,
baixar relatório/evidências. É a superfície que CI/CD e integrações usam
(`X-API-Key` — ver src/auth.py); a UI web fala com os mesmos endpoints, sem
precisar da chave enquanto o servidor estiver em bind loopback."""
import asyncio
import io
import json
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from src import auth, models, report, run_service, store
from src.events import list_events
from src.settings import uploads_dir

router = APIRouter(dependencies=[Depends(auth.require_api_key)])

TERMINAL_STATUSES = run_service.TERMINAL_STATUSES

# Extensões aceitas pro upload de binário mobile — .aab entra na lista (pra
# não confundir o usuário escondendo a opção), mas é rejeitado com uma
# mensagem clara mais adiante no pipeline (validate_apk, em
# tools/binary_fetch.py) já que ainda não instalamos .aab direto (falta
# bundletool). .zip cobre o export de simulador iOS (Payload/*.app).
_ALLOWED_BINARY_EXTENSIONS = {".apk", ".aab", ".ipa", ".zip"}


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
        **run_service.run_summary_dict(run),
        "bdd_script": run.bdd_script,
        "test_data_keys": sorted(store.get_run_test_data(run.id).keys()),
        "scenarios": [_scenario_dict(s) for s in store.list_scenarios(run.id)],
    }


def _write_upload(raw_file, dest_path: Path) -> int:
    """Copia `raw_file` (o arquivo bruto por baixo de um UploadFile) pra
    `dest_path` em chunks, sem carregar tudo na memória de uma vez — função
    síncrona de propósito, pra rodar dentro de um `asyncio.to_thread`."""
    size = 0
    with open(dest_path, "wb") as out:
        while chunk := raw_file.read(1 << 20):
            size += len(chunk)
            out.write(chunk)
    return size


@router.post("/api/binaries/upload")
async def upload_binary(file: UploadFile = File(...)):
    """Recebe um .apk/.aab/.ipa/.zip da tela de Nova Execução e devolve o
    caminho absoluto onde ficou — a UI manda esse caminho de volta como
    `binary_url` no POST /api/runs (mesmo campo que já aceitava uma URL
    http(s); `fetch_binary`, em tools/binary_fetch.py, reconhece um caminho
    local e copia em vez de baixar). Fica em `uploads_dir()`, uma área de
    estágio: some assim que a run correspondente é provisionada (ver
    `cleanup_staged_upload`) — ou, se a run nunca chegar a existir, é varrido
    depois de um tempo pelo mesmo ciclo de manutenção que faz o prune de
    runs antigas (ver prune.py)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_BINARY_EXTENSIONS:
        allowed = ", ".join(sorted(_ALLOWED_BINARY_EXTENSIONS))
        return JSONResponse(
            status_code=400,
            content={"error": f"Extensão não suportada: '{suffix or '(nenhuma)'}'. Use uma dessas: {allowed}."},
        )

    # Nome de arquivo é só o basename do que o cliente mandou — nunca os
    # componentes de diretório (um client malicioso/estranho não decide onde
    # o arquivo cai no disco; o id aleatório do diretório já cuida de evitar
    # colisão entre uploads concorrentes).
    dest_dir = uploads_dir() / uuid.uuid4().hex
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / Path(file.filename or "app").name

    # `file.file` é o SpooledTemporaryFile/arquivo real por baixo do
    # UploadFile — ler/escrever ele é bloqueante (síncrono), então roda
    # tudo numa thread de uma vez (mesmo padrão de tools/binary_fetch.py)
    # em vez de misturar `await file.read()` com `open()`/`write()`
    # bloqueante direto no corpo da rota async.
    size = await asyncio.to_thread(_write_upload, file.file, dest_path)

    if size == 0:
        shutil.rmtree(dest_dir, ignore_errors=True)
        return JSONResponse(status_code=400, content={"error": "Arquivo enviado está vazio."})

    return {"path": str(dest_path), "filename": dest_path.name, "size": size}


@router.post("/api/runs")
async def create_run(payload: RunCreate):
    try:
        run = run_service.create_run(
            platform=payload.platform,
            bdd_script=payload.bdd_script,
            app_url=payload.app_url,
            binary_url=payload.binary_url,
            binary_auth_secret=payload.binary_auth_secret,
            test_data=payload.test_data,
            llm_provider=payload.llm_provider,
            llm_model=payload.llm_model,
        )
    except run_service.RunServiceError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return run_service.run_summary_dict(run)


@router.get("/api/runs")
async def list_runs(limit: int = 20, offset: int = 0, status: str | None = None, platform: str | None = None):
    return run_service.list_run_summaries(limit=limit, offset=offset, status=status, platform=platform)


@router.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = store.get_run(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "Run not found."})
    return _run_detail_dict(run)


@router.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    try:
        run_service.request_cancel(run_id)
    except run_service.RunNotFoundError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except run_service.RunServiceError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return {"id": run_id, "cancel_requested": True}


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


@router.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request, after: int = 0):
    run = store.get_run(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "Run not found."})

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
    try:
        return JSONResponse(content=run_service.get_report_dict(run_id))
    except (run_service.RunNotFoundError, run_service.RunServiceError) as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@router.get("/api/runs/{run_id}/report.html")
async def get_report_html(run_id: str):
    run = store.get_run(run_id)
    if not run or not run.artifacts_dir:
        return JSONResponse(status_code=404, content={"error": "Report not available yet."})
    report_path = Path(run.artifacts_dir) / "report.html"
    if not report_path.exists():
        return JSONResponse(status_code=404, content={"error": "report.html not found."})
    return FileResponse(report_path, media_type="text/html")


@router.get("/api/runs/{run_id}/report.pdf")
async def get_report_pdf(run_id: str):
    try:
        pdf_path = await report.render_report_pdf(run_id)
    except (ValueError, FileNotFoundError) as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"argus-report-{run_id}.pdf",
    )


@router.get("/api/runs/{run_id}/artifacts.zip")
async def get_artifacts_zip(run_id: str):
    run = store.get_run(run_id)
    if not run or not run.artifacts_dir:
        return JSONResponse(status_code=404, content={"error": "Artifacts not available yet."})
    artifacts_dir = Path(run.artifacts_dir)
    if not artifacts_dir.exists():
        return JSONResponse(status_code=404, content={"error": "Artifacts directory not found."})

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
        return JSONResponse(status_code=404, content={"error": "Evidence not found."})
    path = Path(evidence.path)
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "Evidence file not found on disk."})
    return FileResponse(path)


@router.get("/api/runs/{run_id}/{file_path:path}")
async def get_report_asset(run_id: str, file_path: str):
    """Serve arquivos do diretório de artefatos da run pelo caminho relativo
    usado dentro do próprio `report.html` (`<img src="screenshots/x.png">`).
    Sem isso, abrir o relatório por `GET .../report.html` (em vez do arquivo
    direto no disco) resolve esse `src` relativo contra a URL da API — que
    não tem rota nenhuma pra `.../screenshots/x.png` —, quebrando as imagens
    de evidência (achado ao vivo). Precisa ser a ÚLTIMA rota `/api/runs/
    {run_id}/...` declarada neste arquivo: FastAPI/Starlette casam por
    ordem de registro, então rotas mais específicas (cancel, stream, report,
    report.html, artifacts.zip) sempre vencem antes deste catch-all."""
    run = store.get_run(run_id)
    if not run or not run.artifacts_dir:
        return JSONResponse(status_code=404, content={"error": "Run not found."})
    artifacts_dir = Path(run.artifacts_dir).resolve()
    target = (artifacts_dir / file_path).resolve()
    if not target.is_relative_to(artifacts_dir) or not target.is_file():
        return JSONResponse(status_code=404, content={"error": "File not found."})
    return FileResponse(target)
