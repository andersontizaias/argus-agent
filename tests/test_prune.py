"""Testes de src/prune.py — retenção de runs antigas."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src import db, models, prune, store


def _create_terminated_run(*, finished_days_ago: int, status: str = "passed", artifacts_dir: Path | None = None) -> str:
    run = store.create_run(platform="web", bdd_script="# language: pt\nFuncionalidade: X\n  Cenario: Y\n    Dado algo\n")
    store.update_run_status(run.id, status, started_at=True, finished_at=True)
    if artifacts_dir:
        store.set_run_artifacts_dir(run.id, str(artifacts_dir))
    # `finished_at` precisa ser escrito diretamente — update_run_status só
    # sabe gravar "agora", não uma data arbitrária no passado.
    with db.session_scope() as session:
        db_run = session.get(models.Run, run.id)
        db_run.finished_at = datetime.now(UTC) - timedelta(days=finished_days_ago)
    return run.id


def test_retention_days_defaults_to_30_when_unset():
    assert prune.retention_days() == prune.DEFAULT_RETENTION_DAYS


def test_retention_days_reads_configured_setting():
    store.set_setting("retention_days", "7")
    assert prune.retention_days() == 7


def test_retention_days_falls_back_to_default_on_garbage_value():
    store.set_setting("retention_days", "not-a-number")
    assert prune.retention_days() == prune.DEFAULT_RETENTION_DAYS


def test_prune_removes_old_terminated_runs_and_their_artifacts(tmp_path):
    store.set_setting("retention_days", "30")
    old_dir = tmp_path / "old-run"
    old_dir.mkdir()
    (old_dir / "report.json").write_text("{}")
    old_id = _create_terminated_run(finished_days_ago=31, artifacts_dir=old_dir)

    recent_dir = tmp_path / "recent-run"
    recent_dir.mkdir()
    recent_id = _create_terminated_run(finished_days_ago=1, artifacts_dir=recent_dir)

    removed = prune.prune_old_runs()

    assert removed == 1
    assert store.get_run(old_id) is None
    assert not old_dir.exists()
    assert store.get_run(recent_id) is not None
    assert recent_dir.exists()


def test_prune_never_touches_runs_still_in_progress():
    store.set_setting("retention_days", "1")
    run = store.create_run(platform="web", bdd_script="# language: pt\nFuncionalidade: X\n  Cenario: Y\n    Dado algo\n")
    store.update_run_status(run.id, "running", started_at=True)
    with db.session_scope() as session:
        db_run = session.get(models.Run, run.id)
        db_run.started_at = datetime.now(UTC) - timedelta(days=10)

    removed = prune.prune_old_runs()

    assert removed == 0
    assert store.get_run(run.id) is not None


def test_prune_disabled_when_retention_days_is_zero():
    store.set_setting("retention_days", "0")
    _create_terminated_run(finished_days_ago=365)

    assert prune.prune_old_runs() == 0


def test_prune_is_noop_when_nothing_is_old_enough():
    store.set_setting("retention_days", "30")
    _create_terminated_run(finished_days_ago=1)

    assert prune.prune_old_runs() == 0
