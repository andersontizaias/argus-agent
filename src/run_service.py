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
from src.llm_providers import default_model_setting_name, get_provider

TERMINAL_STATUSES = {"passed", "failed", "error", "canceled"}
VALID_PLATFORMS = {"web", "android", "ios"}
VALID_MODES = {"execute", "explore"}

# Orçamento de ações do modo "explore" (o agente navega sozinho, sem um
# script pra seguir) — limite duro pra conter custo (chamadas de LLM) e o
# raio de ação de um agente agindo contra uma aplicação de verdade sem
# supervisão passo a passo. Ver docstring de src.agent.executor.
DEFAULT_EXPLORE_MAX_ACTIONS = 25
_MAX_EXPLORE_MAX_ACTIONS = 100


class RunServiceError(ValueError):
    """Erro de validação ou de regra de negócio — nunca sobre a run não
    existir (isso é `RunNotFoundError`, tratado à parte porque mapeia pra
    um status HTTP diferente no REST)."""


class RunNotFoundError(LookupError):
    """Run inexistente para o `run_id` informado."""


def create_run(
    *,
    platform: str,
    bdd_script: str = "",
    app_url: str | None = None,
    binary_url: str | None = None,
    binary_auth_secret: str | None = None,
    test_data: dict[str, str] | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    mode: str = "execute",
    max_actions: int | None = None,
    confirmed_non_production: bool = False,
) -> models.Run:
    if platform not in VALID_PLATFORMS:
        raise RunServiceError(f"Invalid platform: {platform}")
    if mode not in VALID_MODES:
        raise RunServiceError(f"Invalid mode: {mode}")
    if platform != "web" and not binary_url:
        raise RunServiceError(f"Platform '{platform}' requires binary_url.")

    if mode == "execute":
        if not bdd_script.strip():
            raise RunServiceError("Empty BDD script.")
        test_data = test_data or {}
        try:
            scenarios = parse_bdd_script(bdd_script)
            validate_test_data(scenarios, test_data)
        except BddParseError as e:
            raise RunServiceError(str(e)) from e
    else:
        # "explore": sem script de entrada — o agente navega sozinho e
        # PRODUZ um. Fricção deliberada: como é um agente agindo sem
        # supervisão passo a passo contra uma aplicação de verdade, exige
        # confirmação explícita de que não é produção (não é uma garantia
        # técnica — não dá pra verificar isso de fato — é uma barreira
        # proposital antes de deixar o agente agir sozinho).
        if not confirmed_non_production:
            raise RunServiceError(
                "Explore mode requires confirmed_non_production=true — confirm this target isn't production."
            )
        bdd_script = ""
        test_data = test_data or {}

    resolved_provider = llm_provider or store.get_setting("default_llm_provider")
    provider = get_provider(resolved_provider) if resolved_provider else None
    if not provider:
        raise RunServiceError("No LLM provider configured (set a default in /config or pass llm_provider).")
    # O modelo é um setting por provider (cada provider configurado guarda
    # o seu preferido) — não um único global, senão trocar de provider
    # default perderia o modelo configurado dos outros.
    resolved_model = llm_model or store.get_setting(default_model_setting_name(provider))

    resolved_max_actions = DEFAULT_EXPLORE_MAX_ACTIONS if max_actions is None else max_actions
    if mode == "explore" and not (1 <= resolved_max_actions <= _MAX_EXPLORE_MAX_ACTIONS):
        raise RunServiceError(f"max_actions must be between 1 and {_MAX_EXPLORE_MAX_ACTIONS}.")

    return store.create_run(
        platform=platform,
        mode=mode,
        app_url=app_url,
        binary_url=binary_url,
        binary_auth_secret=binary_auth_secret,
        bdd_script=bdd_script,
        test_data=test_data,
        llm_provider=resolved_provider,
        llm_model=resolved_model,
        max_actions=resolved_max_actions,
        confirmed_non_production=confirmed_non_production,
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
        "mode": run.mode,
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
        "max_actions": run.max_actions,
        "generated_bdd_script": run.generated_bdd_script,
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
