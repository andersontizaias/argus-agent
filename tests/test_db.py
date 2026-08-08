import sqlalchemy

from src import db


def test_session_scope_commits_on_success():
    with db.session_scope() as session:
        session.execute(sqlalchemy.text("SELECT 1"))


def test_session_scope_rolls_back_on_error():
    try:
        with db.session_scope() as session:
            session.execute(sqlalchemy.text("SELECT 1"))
            raise ValueError("boom")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError to propagate")


def test_wal_and_foreign_keys_pragmas_active():
    with db.engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        fk = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert mode == "wal"
    assert fk == 1
