"""Argus Agent — casos de uso de runs compartilhados entre as superfícies de
integração (REST, MCP, e A2A numa fase futura). Validação e regras de
negócio (plataforma válida, binary_url obrigatório fora de web, script BDD
parseável, provider LLM configurado) ficam aqui uma única vez — cada
fachada só traduz o resultado pro seu próprio formato (REST: JSONResponse
400/404; MCP: dict `{"error": ...}`)."""
from __future__ import annotations

import json
from pathlib import Path

from src import models, store
from src.bdd import BddParseError, parse_bdd_script, validate_test_data
from src.llm_providers import get_provider

TERMINAL_STATUSES = {"passed", "failed", "error", "canceled"}
VALID_PLATFORMS = {"web", "android", "ios"}


class RunServiceError(ValueError):
    """Erro de validação ou de regra de negócio — nunca sobre a run não
    existir (isso é `RunNotFoundError`, tratado à parte porque mapeia pra
    um status HTTP diferente no REST)."""


class RunNotFoundError(LookupError):
    """Run inexistente para o `run_id` informado."""


def create_run(
    *,
    platform: str,
    bdd_script: str,
    app_url: str | None = None,
    binary_url: str | None = None,
    binary_auth_secret: str | None = None,
    test_data: dict[str, str] | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> models.Run:
    if platform not in VALID_PLATFORMS:
        raise RunServiceError(f"Invalid platform: {platform}")
    if platform != "web" and not binary_url:
        raise RunServiceError(f"Platform '{platform}' requires binary_url.")
    if not bdd_script.strip():
        raise RunServiceError("Empty BDD script.")

    test_data = test_data or {}
    try:
        scenarios = parse_bdd_script(bdd_script)
        validate_test_data(scenarios, test_data)
    except BddParseError as e:
        raise RunServiceError(str(e)) from e

    resolved_provider = llm_provider or store.get_setting("default_llm_provider")
    resolved_model = llm_model or store.get_setting("default_llm_model")
    if not resolved_provider or not get_provider(resolved_provider):
        raise RunServiceError("No LLM provider configured (set a default in /config or pass llm_provider).")

    return store.create_run(
        platform=platform,
        app_url=app_url,
        binary_url=binary_url,
        binary_auth_secret=binary_auth_secret,
        bdd_script=bdd_script,
        test_data=test_data,
        llm_provider=resolved_provider,
        llm_model=resolved_model,
    )


def request_cancel(run_id: str) -> None:
    run = store.get_run(run_id)
    if not run:
        raise RunNotFoundError(f"Run {run_id} not found.")
    if run.status in TERMINAL_STATUSES:
        raise RunServiceError(f"Run has already finished (status: {run.status}).")
    store.request_cancel(run_id)


def run_summary_dict(run: models.Run) -> dict:
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


def get_run_summary(run_id: str) -> dict:
    run = store.get_run(run_id)
    if not run:
        raise RunNotFoundError(f"Run {run_id} not found.")
    return run_summary_dict(run)


def get_report_dict(run_id: str) -> dict:
    run = store.get_run(run_id)
    if not run:
        raise RunNotFoundError(f"Run {run_id} not found.")
    if not run.artifacts_dir:
        raise RunServiceError("Report not available yet — the run hasn't finished.")
    report_path = Path(run.artifacts_dir) / "report.json"
    if not report_path.exists():
        raise RunServiceError("report.json not found.")
    return json.loads(report_path.read_text(encoding="utf-8"))


def list_run_summaries(
    *, limit: int = 20, offset: int = 0, status: str | None = None, platform: str | None = None
) -> dict:
    limit = max(1, min(limit, 100))
    runs = store.list_runs(limit=limit, offset=offset, status=status, platform=platform)
    total = store.count_runs(status=status, platform=platform)
    return {"runs": [run_summary_dict(r) for r in runs], "total": total, "limit": limit, "offset": offset}
