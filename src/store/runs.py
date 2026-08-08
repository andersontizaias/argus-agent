"""Argus Agent — CRUD da tabela `runs`."""
import json
from datetime import UTC, datetime

from src import crypto, db, models


def create_run(
    *,
    platform: str,
    bdd_script: str,
    test_data: dict[str, str] | None = None,
    app_url: str | None = None,
    binary_url: str | None = None,
    binary_auth_secret: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> models.Run:
    test_data_enc = crypto.encrypt_secret(json.dumps(test_data or {}))
    row = models.Run(
        platform=platform,
        app_url=app_url,
        binary_url=binary_url,
        binary_auth_secret=binary_auth_secret,
        bdd_script=bdd_script,
        test_data_enc=test_data_enc,
        llm_provider=llm_provider,
        llm_model=llm_model,
        status="queued",
    )
    with db.session_scope() as session:
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    return row


def get_run(run_id: str) -> models.Run | None:
    with db.session_scope() as session:
        row = session.get(models.Run, run_id)
        if row:
            session.expunge(row)
        return row


def get_run_test_data(run_id: str) -> dict[str, str]:
    run = get_run(run_id)
    if not run or not run.test_data_enc:
        return {}
    return json.loads(crypto.decrypt_secret(run.test_data_enc))


def update_run_status(
    run_id: str,
    status: str,
    *,
    error: str | None = None,
    started_at: bool = False,
    finished_at: bool = False,
) -> None:
    with db.session_scope() as session:
        run = session.get(models.Run, run_id)
        if not run:
            return
        run.status = status
        if error is not None:
            run.error = error
        if started_at:
            run.started_at = datetime.now(UTC)
        if finished_at:
            run.finished_at = datetime.now(UTC)


def set_run_totals(run_id: str, *, total: int, passed: int, failed: int) -> None:
    with db.session_scope() as session:
        run = session.get(models.Run, run_id)
        if not run:
            return
        run.scenarios_total = total
        run.scenarios_passed = passed
        run.scenarios_failed = failed


def add_run_usage(run_id: str, *, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
    """Incrementa (não substitui) — chamada uma vez por passo, então o
    total da run vai crescendo conforme os passos rodam (visível ao vivo
    via SSE, mesmo padrão dos totais de cenários)."""
    with db.session_scope() as session:
        run = session.get(models.Run, run_id)
        if not run:
            return
        run.tokens_in += tokens_in
        run.tokens_out += tokens_out
        run.cost_usd += cost_usd


def set_run_artifacts_dir(run_id: str, path: str) -> None:
    with db.session_scope() as session:
        run = session.get(models.Run, run_id)
        if run:
            run.artifacts_dir = path


def set_run_job_id(run_id: str, job_id: str) -> None:
    with db.session_scope() as session:
        run = session.get(models.Run, run_id)
        if run:
            run.job_id = job_id


def request_cancel(run_id: str) -> None:
    with db.session_scope() as session:
        run = session.get(models.Run, run_id)
        if run:
            run.cancel_requested = True


def is_cancel_requested(run_id: str) -> bool:
    with db.session_scope() as session:
        run = session.get(models.Run, run_id)
        return bool(run and run.cancel_requested)


def list_queued_run_ids() -> list[str]:
    with db.session_scope() as session:
        rows = (
            session.query(models.Run.id)
            .filter(models.Run.status == "queued")
            .order_by(models.Run.created_at)
            .all()
        )
        return [r[0] for r in rows]


def _filtered_runs_query(session, *, status: str | None, platform: str | None):
    query = session.query(models.Run)
    if status:
        query = query.filter(models.Run.status == status)
    if platform:
        query = query.filter(models.Run.platform == platform)
    return query


def list_runs(
    *, limit: int = 20, offset: int = 0, status: str | None = None, platform: str | None = None,
) -> list[models.Run]:
    with db.session_scope() as session:
        query = _filtered_runs_query(session, status=status, platform=platform)
        rows = query.order_by(models.Run.created_at.desc()).offset(offset).limit(limit).all()
        session.expunge_all()
        return rows


def count_runs(*, status: str | None = None, platform: str | None = None) -> int:
    with db.session_scope() as session:
        return _filtered_runs_query(session, status=status, platform=platform).count()
