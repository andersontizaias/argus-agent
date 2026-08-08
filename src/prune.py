"""Argus Agent — retenção de runs antigas.

Apaga artefatos em disco (screenshots, report.json/html) + a linha da run no
banco (cascata cuida de cenários/passos/evidências/eventos, ver models.py)
para runs já TERMINADAS (passed/failed/error/canceled — nunca queued/
provisioning/running, mesmo se antigas: seriam runs travadas, um problema à
parte) há mais de `retention_days`. Chamado periodicamente pelo worker
(ver PRUNE_INTERVAL_SECONDS em src/worker.py), nunca a cada poll — é uma
tarefa de manutenção, não algo que precisa reagir em tempo real."""
import logging
import shutil
from datetime import UTC, datetime, timedelta

from src import store

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 30


def retention_days() -> int:
    """0 (ou negativo) desliga o prune — retenção "para sempre", op-in
    explícito do usuário via /api/config, não o comportamento padrão."""
    raw = store.get_setting("retention_days")
    if raw and raw.lstrip("-").isdigit():
        return int(raw)
    return DEFAULT_RETENTION_DAYS


def prune_old_runs() -> int:
    """Retorna quantas runs foram removidas."""
    days = retention_days()
    if days <= 0:
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=days)
    removed = 0
    for run in store.list_terminated_runs_older_than(cutoff):
        if run.artifacts_dir:
            shutil.rmtree(run.artifacts_dir, ignore_errors=True)
        store.delete_run(run.id)
        removed += 1

    if removed:
        logger.info("Prune: %d run(s) removida(s) (retenção de %d dias).", removed, days)
    return removed
