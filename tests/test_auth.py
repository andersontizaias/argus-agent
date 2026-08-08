import pytest
from fastapi import HTTPException

from src import auth, store

pytestmark = pytest.mark.anyio


async def test_require_api_key_bypasses_on_loopback_without_flag(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", True)
    monkeypatch.setattr(auth, "REQUIRE_API_KEY", False)
    await auth.require_api_key(x_api_key=None)  # não deve levantar


async def test_require_api_key_enforced_on_loopback_when_flag_set(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", True)
    monkeypatch.setattr(auth, "REQUIRE_API_KEY", True)
    with pytest.raises(HTTPException) as exc_info:
        await auth.require_api_key(x_api_key=None)
    assert exc_info.value.status_code == 401


async def test_require_api_key_enforced_off_loopback(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", False)
    with pytest.raises(HTTPException) as exc_info:
        await auth.require_api_key(x_api_key=None)
    assert exc_info.value.status_code == 401


async def test_require_api_key_accepts_valid_key(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", False)
    _row, full_key = store.create_api_key("ci-token")
    await auth.require_api_key(x_api_key=full_key)  # não deve levantar


async def test_require_api_key_rejects_invalid_key(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", False)
    with pytest.raises(HTTPException) as exc_info:
        await auth.require_api_key(x_api_key="argus_bad_key")
    assert exc_info.value.status_code == 401
