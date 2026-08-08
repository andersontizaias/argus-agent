"""Argus Agent — CRUD das tabelas `scenarios` e `steps`."""
from datetime import UTC, datetime

from src import db, models
from src.bdd import ParsedScenario


def replace_scenarios(run_id: str, parsed: list[ParsedScenario]) -> None:
    """Grava os cenários/passos parseados do BDD para uma run — chamado uma
    vez por run, logo após o parse. Remove qualquer cenário pré-existente
    antes (idempotente, caso o nó de parsing seja reexecutado numa
    retomada)."""
    with db.session_scope() as session:
        existing_scenario_ids = [
            row[0] for row in session.query(models.Scenario.id).filter(models.Scenario.run_id == run_id)
        ]
        if existing_scenario_ids:
            # Steps (e evidências, que referenciam step_id) têm FK pra
            # Scenario sem cascade a nível de banco — com PRAGMA
            # foreign_keys=ON, apagar o Scenario primeiro violaria a FK.
            session.query(models.Evidence).filter(models.Evidence.run_id == run_id).update(
                {"step_id": None}, synchronize_session=False,
            )
            session.query(models.Step).filter(models.Step.scenario_id.in_(existing_scenario_ids)).delete(
                synchronize_session=False,
            )
            session.query(models.Scenario).filter(models.Scenario.run_id == run_id).delete(
                synchronize_session=False,
            )
        for position, scenario in enumerate(parsed):
            row = models.Scenario(
                run_id=run_id,
                position=position,
                name=scenario.name,
                tags=",".join(scenario.tags),
                status="pending",
            )
            session.add(row)
            session.flush()
            for step_position, step in enumerate(scenario.steps):
                session.add(models.Step(
                    scenario_id=row.id,
                    position=step_position,
                    keyword=step.keyword,
                    text=step.text,
                    status="pending",
                ))


def list_scenarios(run_id: str) -> list[models.Scenario]:
    with db.session_scope() as session:
        rows = (
            session.query(models.Scenario)
            .filter(models.Scenario.run_id == run_id)
            .order_by(models.Scenario.position)
            .all()
        )
        session.expunge_all()
        return rows


def get_scenario(scenario_id: str) -> models.Scenario | None:
    with db.session_scope() as session:
        row = session.get(models.Scenario, scenario_id)
        if row:
            session.expunge(row)
        return row


def update_scenario_status(
    scenario_id: str,
    status: str,
    *,
    started_at: bool = False,
    finished_at: bool = False,
    failure_reason: str | None = None,
) -> None:
    with db.session_scope() as session:
        row = session.get(models.Scenario, scenario_id)
        if not row:
            return
        row.status = status
        if failure_reason is not None:
            row.failure_reason = failure_reason
        if started_at:
            row.started_at = datetime.now(UTC)
        if finished_at:
            row.finished_at = datetime.now(UTC)


def list_steps(scenario_id: str) -> list[models.Step]:
    with db.session_scope() as session:
        rows = (
            session.query(models.Step)
            .filter(models.Step.scenario_id == scenario_id)
            .order_by(models.Step.position)
            .all()
        )
        session.expunge_all()
        return rows


def update_step_status(
    step_id: str,
    status: str,
    *,
    started_at: bool = False,
    finished_at: bool = False,
    error: str | None = None,
    attempts: int | None = None,
    duration_ms: int | None = None,
) -> None:
    with db.session_scope() as session:
        row = session.get(models.Step, step_id)
        if not row:
            return
        row.status = status
        if error is not None:
            row.error = error
        if attempts is not None:
            row.attempts = attempts
        if duration_ms is not None:
            row.duration_ms = duration_ms
        if started_at:
            row.started_at = datetime.now(UTC)
        if finished_at:
            row.finished_at = datetime.now(UTC)
