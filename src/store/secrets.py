"""Argus Agent — CRUD de secrets (chaves LLM, auth de fontes de binário).

Valores são cifrados/decifrados pelo caller (src/crypto.py) — este módulo só
persiste o que recebe. Um valor vazio DELETA a linha em vez de gravar um
placeholder, mesmo padrão do phalanx (src/store/config.py)."""
from src import db, models


def get_secret(name: str) -> str | None:
    with db.session_scope() as session:
        row = session.get(models.Secret, name)
        return row.value_enc if row else None


def set_secret(name: str, value_enc: str) -> None:
    with db.session_scope() as session:
        row = session.get(models.Secret, name)
        if not value_enc:
            if row:
                session.delete(row)
            return
        if row:
            row.value_enc = value_enc
        else:
            session.add(models.Secret(name=name, value_enc=value_enc))


def list_secret_names() -> list[str]:
    with db.session_scope() as session:
        return [row.name for row in session.query(models.Secret).order_by(models.Secret.name)]
