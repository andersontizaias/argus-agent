"""Configuração global de testes.

Define ARGUS_DB_PATH/ARGUS_SECRET_KEY/ARGUS_ARTIFACTS_DIR num diretório
temporário ANTES de qualquer `import src...` acontecer — src/db.py calcula
a DATABASE_URL uma vez, na importação do módulo, então as env vars precisam
existir antes disso (conftest.py é carregado pelo pytest antes da coleta dos
módulos de teste)."""
import os
import tempfile
from pathlib import Path

_tmp_dir = Path(tempfile.mkdtemp(prefix="argus-test-"))
os.environ.setdefault("ARGUS_DB_PATH", str(_tmp_dir / "test.db"))
os.environ.setdefault("ARGUS_ARTIFACTS_DIR", str(_tmp_dir / "artifacts"))
os.environ.setdefault("ARGUS_HOST", "127.0.0.1")

if "ARGUS_SECRET_KEY" not in os.environ:
    from cryptography.fernet import Fernet

    os.environ["ARGUS_SECRET_KEY"] = Fernet.generate_key().decode()

import pytest

from src import store


@pytest.fixture(scope="session", autouse=True)
def _ensure_db():
    store.init_db()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Cada teste roda contra o mesmo arquivo SQLite (mais rápido que recriar
    o schema a cada teste) — limpa as tabelas mutáveis antes de cada teste
    para eliminar contaminação entre eles."""
    from src import db, models

    with db.session_scope() as session:
        for model in (models.Secret, models.Setting, models.ApiKey, models.Run):
            session.query(model).delete()
    yield
