"""Argus Agent — configuração de ambiente e paths."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


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


HOST = os.getenv("ARGUS_HOST", "127.0.0.1")
PORT = int(os.getenv("ARGUS_PORT", "8765"))
REQUIRE_API_KEY = os.getenv("ARGUS_REQUIRE_API_KEY", "false").lower() == "true"
IS_LOOPBACK = HOST in ("127.0.0.1", "localhost", "::1")
