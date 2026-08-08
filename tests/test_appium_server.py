"""Testes de src/tools/appium_server.py — sobe/derruba o processo Appium,
tudo mockado (subprocess + requests), sem depender de Appium instalado pra
rodar a suíte."""
import asyncio
import itertools

import pytest

from src.tools import appium_server as aps

pytestmark = pytest.mark.anyio


class _FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


async def test_start_appium_raises_clear_error_when_binary_missing(monkeypatch):
    async def fake_create_subprocess_exec(*_a, **_kw):
        raise FileNotFoundError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    with pytest.raises(aps.AppiumError, match="não encontrado no PATH"):
        await aps.start_appium(4723)


async def test_start_appium_returns_handle_once_status_is_ready(monkeypatch):
    process = _FakeProcess()

    async def fake_create_subprocess_exec(*_a, **_kw):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(aps.requests, "get", lambda *_a, **_kw: _FakeResponse(200))

    handle = await aps.start_appium(4723)
    assert handle.port == 4723
    assert handle.url == "http://127.0.0.1:4723"


async def test_start_appium_stops_process_if_never_becomes_ready(monkeypatch):
    process = _FakeProcess()

    async def fake_create_subprocess_exec(*_a, **_kw):
        return process

    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(aps.requests, "get", lambda *_a, **_kw: _FakeResponse(500))

    # `time.monotonic` é o MESMO módulo usado internamente pelo `loop.time()`
    # do asyncio — patchear com uma lista curta de valores fixos estoura
    # StopIteration assim que qualquer chamada asyncio interna (ex.: o
    # `asyncio.wait_for` usado dentro de `stop_appium`) também consome do
    # iterador. `repeat` no final cobre qualquer chamada extra sem quebrar.
    times = itertools.chain([0], itertools.repeat(1000))
    monkeypatch.setattr(aps.time, "monotonic", lambda: next(times))

    with pytest.raises(aps.AppiumError, match="não respondeu em"):
        await aps.start_appium(4723, start_timeout_seconds=5)
    assert process.terminated is True


async def test_start_appium_raises_if_process_exits_early(monkeypatch):
    process = _FakeProcess(returncode=1)

    async def fake_create_subprocess_exec(*_a, **_kw):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(aps.requests, "get", lambda *_a, **_kw: _FakeResponse(500))

    with pytest.raises(aps.AppiumError, match="encerrou sozinho"):
        await aps.start_appium(4723)


async def test_stop_appium_terminates_process(monkeypatch):
    process = _FakeProcess()
    handle = aps.AppiumHandle(port=4723, process=process)
    await aps.stop_appium(handle)
    assert process.terminated is True


async def test_stop_appium_noop_when_already_exited(monkeypatch):
    process = _FakeProcess(returncode=0)
    handle = aps.AppiumHandle(port=4723, process=process)
    await aps.stop_appium(handle)
    assert process.terminated is False  # já tinha saído — nada a fazer
