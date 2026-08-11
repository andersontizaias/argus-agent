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
os.environ.setdefault("ARGUS_UPLOADS_DIR", str(_tmp_dir / "uploads"))
os.environ.setdefault("ARGUS_HOST", "127.0.0.1")

if "ARGUS_SECRET_KEY" not in os.environ:
    from cryptography.fernet import Fernet

    os.environ["ARGUS_SECRET_KEY"] = Fernet.generate_key().decode()

import pytest

from src import store


@pytest.fixture
def anyio_backend():
    # anyio ships its own pytest plugin (registered automatically — see
    # pyproject: nenhuma dependência extra precisa ser adicionada); sem
    # fixar o backend, testes marcados @pytest.mark.anyio rodariam em
    # dobro (asyncio + trio), e trio não está instalado.
    return "asyncio"


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
        # Ordem importa: com PRAGMA foreign_keys=ON (src/db.py), apagar Run
        # antes dos filhos (Scenario/Step/Evidence/RunEvent) violaria a FK —
        # bulk delete não dispara o cascade ORM (esse só age em session.delete
        # de um objeto com o relationship carregado), então a ordem tem que
        # ser filho-antes-do-pai manualmente.
        for model in (
            models.Evidence, models.Step, models.Scenario, models.RunEvent,
            models.Run, models.Secret, models.Setting, models.ApiKey,
        ):
            session.query(model).delete()
    yield
