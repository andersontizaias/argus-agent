"""Argus Agent — CRUD da tabela `evidences`."""
from src import db, models


def add_evidence(run_id: str, step_id: str | None, type_: str, label: str, path: str) -> models.Evidence:
    row = models.Evidence(run_id=run_id, step_id=step_id, type=type_, label=label, path=path)
    with db.session_scope() as session:
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    return row


def list_evidences(run_id: str) -> list[models.Evidence]:
    with db.session_scope() as session:
        rows = (
            session.query(models.Evidence)
            .filter(models.Evidence.run_id == run_id)
            .order_by(models.Evidence.created_at)
            .all()
        )
        session.expunge_all()
        return rows
