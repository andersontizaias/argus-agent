"""Argus Agent — configuração de ambiente e paths."""
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _read_version() -> str:
    """Fonte única de verdade: o `version` do pyproject.toml, lido via
    metadata do pacote instalado (hatchling registra isso no build feito
    por `uv sync`) — nunca duplicado à mão em main.py/release.yml/UI."""
    try:
        return version("argus-agent")
    except PackageNotFoundError:  # pragma: no cover — só em ambiente sem `uv sync`
        return "0.0.0-dev"


VERSION = _read_version()


def artifacts_dir() -> Path:
    explicit = os.getenv("ARGUS_ARTIFACTS_DIR")
    path = Path(explicit).expanduser() if explicit else Path.home() / ".argus" / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def checkpoints_db_path() -> Path:
    explicit = os.getenv("ARGUS_DB_PATH")
    base = Path(explicit).expanduser().parent if explicit else Path.home() / ".argus"
    base.mkdir(parents=True, exist_ok=True)
    return base / "checkpoints.db"


def _env_flag(name: str, default: bool = False) -> bool:
    """"1"/"true"/"yes"/"on" contam como verdadeiro (case-insensitive) —
    aceitar só o literal "true" é uma pegadinha comum: `FLAG=1`, a
    convenção mais usada em shell/Unix, silenciosamente virava False."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


HOST = os.getenv("ARGUS_HOST", "127.0.0.1")
PORT = int(os.getenv("ARGUS_PORT", "8765"))
REQUIRE_API_KEY = _env_flag("ARGUS_REQUIRE_API_KEY")
IS_LOOPBACK = HOST in ("127.0.0.1", "localhost", "::1")
