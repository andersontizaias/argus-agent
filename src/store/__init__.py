"""Argus Agent — façade de store: re-exporta os submódulos por domínio.

Call sites usam `from src import store; store.get_secret(...)` sem precisar
saber em qual submódulo a função mora — mesmo padrão do phalanx-agents
(src/store/__init__.py lá)."""
from src.store._shared import init_db
from src.store.api_keys import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
    verify_api_key,
)
from src.store.secrets import get_secret, list_secret_names, set_secret
from src.store.settings import get_setting, set_setting

__all__ = [
    "create_api_key",
    "get_secret",
    "get_setting",
    "init_db",
    "list_api_keys",
    "list_secret_names",
    "revoke_api_key",
    "set_secret",
    "set_setting",
    "verify_api_key",
]
