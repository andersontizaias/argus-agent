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
import time
from datetime import UTC, datetime, timedelta

from src import store
from src.settings import uploads_dir

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 30

# Uploads de binário (.apk/.aab/.ipa/.zip via POST /api/binaries/upload) são
# copiados pro artifacts_dir da run e apagados assim que ela é provisionada
# (ver cleanup_staged_upload em tools/binary_fetch.py) — o que sobra aqui
# depois de algumas horas é upload órfão: usuário escolheu o arquivo, saiu
# da tela sem enviar o formulário, e nunca chegou a existir uma run que
# fosse limpar isso. Retenção curta e fixa (não configurável como a de
# runs): é lixo de formulário abandonado, não histórico que alguém queira
# preservar.
STALE_UPLOAD_HOURS = 6


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


def prune_stale_uploads() -> int:
    """Retorna quantos diretórios de upload órfão foram removidos."""
    cutoff = time.time() - STALE_UPLOAD_HOURS * 3600
    removed = 0
    for entry in uploads_dir().iterdir():
        if not entry.is_dir():
            continue  # uploads_dir() só devia ter as pastas por upload (uuid), mas não confia cegamente
        try:
            stale = entry.stat().st_mtime < cutoff
        except OSError:
            continue
        if stale:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1

    if removed:
        logger.info("Prune: %d upload(s) de binário órfão(s) removido(s).", removed)
    return removed
