"""Argus Agent — CRUD de settings não-secretos (provider default, AVD, device iOS...)."""
from src import db, models


def get_setting(key: str, default: str = "") -> str:
    with db.session_scope() as session:
        row = session.get(models.Setting, key)
        return row.value if row else default


def set_setting(key: str, value: str) -> None:
    with db.session_scope() as session:
        row = session.get(models.Setting, key)
        if row:
            row.value = value
        else:
            session.add(models.Setting(key=key, value=value))
