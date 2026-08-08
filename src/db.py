"""
Argus Agent — Database Engine & Session Management (SQLite)

Single-machine, instalação nativa: SQLite em vez de Postgres (sem serviço
externo para instalar). WAL + busy_timeout resolvem a concorrência real do
projeto — API e worker são dois processos escrevendo no mesmo arquivo, mas
o volume é baixo (1-2 runs simultâneas; o gargalo é o emulador/browser, não
o banco).
"""
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def _default_db_path() -> Path:
    return Path.home() / ".argus" / "argus.db"


def _database_url() -> str:
    explicit = os.getenv("ARGUS_DB_PATH")
    path = Path(explicit).expanduser() if explicit else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


DATABASE_URL = _database_url()

engine = create_engine(
    DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """WAL permite leitor+escritor concorrentes sem lock exclusivo; busy_timeout
    (30s, casado com connect_args acima) faz uma escrita concorrente esperar em
    vez de falhar na hora com "database is locked"; foreign_keys é opt-in no
    SQLite por padrão."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
