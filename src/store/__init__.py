"""Argus Agent — façade de store: re-exporta os submódulos por domínio.

Call sites usam `from src import store; store.get_secret(...)` sem precisar
saber em qual submódulo a função mora — mesmo padrão do phalanx-agents
(src/store/__init__.py lá)."""
from src.store._shared import init_db
from src.store.api_keys import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
    verify_api_key,
)
from src.store.evidences import add_evidence, list_evidences
from src.store.runs import (
    create_run,
    get_run,
    get_run_test_data,
    is_cancel_requested,
    list_queued_run_ids,
    list_runs,
    request_cancel,
    set_run_artifacts_dir,
    set_run_job_id,
    set_run_totals,
    update_run_status,
)
from src.store.scenarios import (
    get_scenario,
    list_scenarios,
    list_steps,
    replace_scenarios,
    update_scenario_status,
    update_step_status,
)
from src.store.secrets import get_secret, list_secret_names, set_secret
from src.store.settings import get_setting, set_setting

__all__ = [
    "add_evidence",
    "create_api_key",
    "create_run",
    "get_run",
    "get_run_test_data",
    "get_scenario",
    "get_secret",
    "get_setting",
    "init_db",
    "is_cancel_requested",
    "list_api_keys",
    "list_evidences",
    "list_queued_run_ids",
    "list_runs",
    "list_scenarios",
    "list_secret_names",
    "list_steps",
    "replace_scenarios",
    "request_cancel",
    "revoke_api_key",
    "set_run_artifacts_dir",
    "set_run_job_id",
    "set_run_totals",
    "set_secret",
    "set_setting",
    "update_run_status",
    "update_scenario_status",
    "update_step_status",
    "verify_api_key",
]
