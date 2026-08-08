"""Argus Agent — CRUD de API keys de máquina (auth para CI/CD).

A chave completa (`argus_<prefix>_<random>`) só existe em memória na criação —
o que fica persistido é `prefix` (para lookup) + hash argon2 do valor
completo. Verificação sempre recalcula o hash e compara, nunca reconstrói
a chave a partir do banco."""
import secrets as pysecrets
import uuid
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from src import db, models

_hasher = PasswordHasher()


def create_api_key(name: str) -> tuple[models.ApiKey, str]:
    """Retorna (registro, chave_em_claro). A chave em claro nunca é persistida
    — é responsabilidade do caller mostrá-la ao usuário uma única vez."""
    prefix = uuid.uuid4().hex[:8]
    secret_part = pysecrets.token_urlsafe(32)
    full_key = f"argus_{prefix}_{secret_part}"

    row = models.ApiKey(name=name, prefix=prefix, key_hash=_hasher.hash(full_key))
    with db.session_scope() as session:
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    return row, full_key


def list_api_keys() -> list[models.ApiKey]:
    with db.session_scope() as session:
        rows = session.query(models.ApiKey).order_by(models.ApiKey.created_at.desc()).all()
        session.expunge_all()
        return rows


def revoke_api_key(key_id: str) -> bool:
    with db.session_scope() as session:
        row = session.get(models.ApiKey, key_id)
        if not row:
            return False
        row.revoked = True
        return True


def verify_api_key(full_key: str) -> models.ApiKey | None:
    """Valida uma chave recebida via header X-API-Key. Retorna o registro se
    válida e não revogada, senão None. Atualiza last_used_at em caso de sucesso."""
    if not full_key.startswith("argus_"):
        return None
    parts = full_key.split("_", 2)
    if len(parts) != 3:
        return None
    prefix = parts[1]

    with db.session_scope() as session:
        candidates = (
            session.query(models.ApiKey)
            .filter(models.ApiKey.prefix == prefix, models.ApiKey.revoked.is_(False))
            .all()
        )
        for row in candidates:
            try:
                _hasher.verify(row.key_hash, full_key)
            except VerifyMismatchError:
                continue
            row.last_used_at = datetime.now(UTC)
            session.flush()
            session.expunge(row)
            return row
    return None
