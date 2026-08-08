import pytest
from fastapi import HTTPException
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

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


# ─── is_authorized (regra pura) ──────────────────────────────────────────


def test_is_authorized_true_on_loopback_without_flag_even_with_no_key(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", True)
    monkeypatch.setattr(auth, "REQUIRE_API_KEY", False)
    assert auth.is_authorized(None) is True


def test_is_authorized_false_without_key_when_required(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", True)
    monkeypatch.setattr(auth, "REQUIRE_API_KEY", True)
    assert auth.is_authorized(None) is False


def test_is_authorized_true_with_valid_key_off_loopback(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", False)
    _row, full_key = store.create_api_key("ci-token")
    assert auth.is_authorized(full_key) is True


def test_is_authorized_false_with_invalid_key_off_loopback(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", False)
    assert auth.is_authorized("argus_bad_key") is False


# ─── ApiKeyMiddleware (usado pelo sub-app Starlette do MCP) ──────────────


def _app_with_middleware():
    async def ok(_request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/ping", ok)])
    app.add_middleware(auth.ApiKeyMiddleware)
    return app


def test_middleware_allows_request_on_loopback_without_flag(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", True)
    monkeypatch.setattr(auth, "REQUIRE_API_KEY", False)
    client = TestClient(_app_with_middleware())
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.text == "ok"


def test_middleware_rejects_request_without_key_off_loopback(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", False)
    client = TestClient(_app_with_middleware())
    response = client.get("/ping")
    assert response.status_code == 401


def test_middleware_accepts_valid_key_header_off_loopback(monkeypatch):
    monkeypatch.setattr(auth, "IS_LOOPBACK", False)
    _row, full_key = store.create_api_key("ci-token")
    client = TestClient(_app_with_middleware())
    response = client.get("/ping", headers={"X-API-Key": full_key})
    assert response.status_code == 200
