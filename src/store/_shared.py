"""Argus Agent — helpers compartilhados entre os submódulos de store."""
from src import (
    db,
    models,
)


def init_db() -> None:
    """Garante que o schema existe. Em dev/test, cria as tabelas direto do
    metadata (mais rápido que rodar alembic toda hora); em produção real o
    schema já foi criado por `alembic upgrade head` no bootstrap/release."""
    models.Base.metadata.create_all(bind=db.engine)
