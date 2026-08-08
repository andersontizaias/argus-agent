"""Argus Agent — publicação de eventos de progresso de uma run.

Grava em `run_events` (não Redis pub/sub) — o `id` autoincrement da tabela
serve de número de sequência: um consumidor (SSE, na fase F2) que reconecta
pede `?after=seq` e recupera exatamente o que perdeu, sem depender de estar
conectado no momento da publicação. `payload` nunca deve conter a massa de
testes em claro (ver src/bdd.py — steps.text guarda só o placeholder, nunca
o valor resolvido, e este módulo respeita o mesmo contrato: só recebe o que
os nós já consideraram seguro publicar)."""
from typing import Any

from src import db, models


def publish_event(run_id: str, type_: str, payload: dict[str, Any] | None = None) -> None:
    with db.session_scope() as session:
        session.add(models.RunEvent(run_id=run_id, type=type_, payload=payload or {}))


def list_events(run_id: str, *, after_seq: int = 0) -> list[models.RunEvent]:
    with db.session_scope() as session:
        rows = (
            session.query(models.RunEvent)
            .filter(models.RunEvent.run_id == run_id, models.RunEvent.id > after_seq)
            .order_by(models.RunEvent.id)
            .all()
        )
        session.expunge_all()
        return rows
