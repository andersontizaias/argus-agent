"""Testes de src/tools/device_ios.py — gestão de simulador via `simctl`,
tudo mockado (não depende de Xcode instalado pra rodar a suíte; a
verificação com simulador de verdade é manual/local, ver PLANO.md)."""
import asyncio
import itertools
from pathlib import Path

import pytest

from src.tools import device_ios as di

pytestmark = pytest.mark.anyio

_DEVICES_JSON_ONE_BOOTED = """{
  "devices": {
    "com.apple.CoreSimulator.SimRuntime.iOS-17-5": [
      {"udid": "AAAA-BOOTED", "name": "iPhone 15", "state": "Booted", "isAvailable": true},
      {"udid": "BBBB-SHUTDOWN", "name": "iPhone 14", "state": "Shutdown", "isAvailable": true}
    ],
    "com.apple.CoreSimulator.SimRuntime.iOS-17-0": [
      {"udid": "CCCC-OLD", "name": "iPhone 15", "state": "Shutdown", "isAvailable": true}
    ]
  }
}"""

_DEVICES_JSON_NONE_MATCHING = """{"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-17-5": []}}"""


async def test_find_simulator_prefers_newest_runtime(monkeypatch):
    async def fake_run(*_a, **_kw):
        return _DEVICES_JSON_ONE_BOOTED

    monkeypatch.setattr(di, "_run", fake_run)
    udid = await di.find_simulator("iPhone 15")
    assert udid == "AAAA-BOOTED"  # runtime iOS-17-5 > iOS-17-0 (mais recente)


async def test_find_simulator_raises_when_not_found(monkeypatch):
    async def fake_run(*_a, **_kw):
        return _DEVICES_JSON_NONE_MATCHING

    monkeypatch.setattr(di, "_run", fake_run)
    with pytest.raises(di.DeviceError, match="não encontrado"):
        await di.find_simulator("iPhone Inexistente")


async def test_list_devices_raises_clear_error_when_xcrun_missing(monkeypatch):
    async def fake_run(*_a, **_kw):
        raise FileNotFoundError()

    monkeypatch.setattr(di, "_run", fake_run)
    with pytest.raises(di.DeviceError, match="Xcode"):
        await di._list_devices_json()


async def test_list_devices_raises_on_invalid_json(monkeypatch):
    async def fake_run(*_a, **_kw):
        return "not json"

    monkeypatch.setattr(di, "_run", fake_run)
    with pytest.raises(di.DeviceError, match="Saída inesperada"):
        await di._list_devices_json()


async def test_is_alive_true_when_booted(monkeypatch):
    async def fake_run(*_a, **_kw):
        return _DEVICES_JSON_ONE_BOOTED

    monkeypatch.setattr(di, "_run", fake_run)
    assert await di.is_alive("AAAA-BOOTED") is True
    assert await di.is_alive("BBBB-SHUTDOWN") is False
    assert await di.is_alive("nao-existe") is False


async def test_is_alive_false_on_error(monkeypatch):
    async def fake_run(*_a, **_kw):
        raise di.DeviceError("boom")

    monkeypatch.setattr(di, "_run", fake_run)
    assert await di.is_alive("qualquer") is False


async def test_boot_simulator_skips_boot_when_already_alive(monkeypatch):
    monkeypatch.setattr(di, "find_simulator", lambda _name: _async_return("AAAA-BOOTED"))
    monkeypatch.setattr(di, "is_alive", lambda _udid: _async_return(True))

    called = {"boot": False}

    async def fake_run(*_a, **_kw):
        called["boot"] = True
        return ""

    monkeypatch.setattr(di, "_run", fake_run)
    handle = await di.boot_simulator("iPhone 15")
    assert handle.udid == "AAAA-BOOTED"
    assert called["boot"] is False


async def test_boot_simulator_boots_and_waits(monkeypatch):
    monkeypatch.setattr(di, "find_simulator", lambda _name: _async_return("BBBB-SHUTDOWN"))

    states = iter([False, True])  # 1ª checagem (antes do boot) = não vivo; 2ª (dentro do wait) = vivo
    monkeypatch.setattr(di, "is_alive", lambda _udid: _async_return(next(states)))

    async def fake_run(*_a, **_kw):
        return ""  # simctl boot bem-sucedido não imprime nada

    monkeypatch.setattr(di, "_run", fake_run)

    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    handle = await di.boot_simulator("iPhone 14")
    assert handle.udid == "BBBB-SHUTDOWN"


async def test_boot_simulator_treats_already_booted_race_as_success(monkeypatch):
    monkeypatch.setattr(di, "find_simulator", lambda _name: _async_return("AAAA-BOOTED"))
    states = iter([False, True])
    monkeypatch.setattr(di, "is_alive", lambda _udid: _async_return(next(states)))

    async def fake_run(*_a, **_kw):
        return "Unable to boot device in current state: Booted"

    monkeypatch.setattr(di, "_run", fake_run)

    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    handle = await di.boot_simulator("iPhone 15")
    assert handle.udid == "AAAA-BOOTED"


async def test_boot_simulator_raises_on_real_boot_failure(monkeypatch):
    monkeypatch.setattr(di, "find_simulator", lambda _name: _async_return("BBBB-SHUTDOWN"))
    monkeypatch.setattr(di, "is_alive", lambda _udid: _async_return(False))

    async def fake_run(*_a, **_kw):
        return "Some unexpected simctl error"

    monkeypatch.setattr(di, "_run", fake_run)

    with pytest.raises(di.DeviceError, match="Falha ao bootar"):
        await di.boot_simulator("iPhone 14")


async def test_wait_for_boot_times_out(monkeypatch):
    monkeypatch.setattr(di, "is_alive", lambda _udid: _async_return(False))

    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    times = itertools.chain([0], itertools.repeat(1000))
    monkeypatch.setattr(di.time, "monotonic", lambda: next(times))

    with pytest.raises(di.DeviceError, match="não terminou de bootar"):
        await di._wait_for_boot("qualquer", timeout_seconds=5)


async def test_shutdown_simulator_never_raises(monkeypatch):
    async def fake_run(*_a, **_kw):
        raise di.DeviceError("simulador já sumiu")

    monkeypatch.setattr(di, "_run", fake_run)
    handle = di.SimulatorHandle(device_name="iPhone 15", udid="AAAA-BOOTED")
    await di.shutdown_simulator(handle)  # não levanta


async def test_simctl_install_success_on_empty_output(monkeypatch):
    async def fake_run(*_a, **_kw):
        return ""

    monkeypatch.setattr(di, "_run", fake_run)
    await di.simctl_install("AAAA-BOOTED", Path("/tmp/App.app"))  # não levanta


async def test_simctl_install_raises_on_nonempty_output(monkeypatch):
    async def fake_run(*_a, **_kw):
        return "Domain=NSPOSIXErrorDomain Code=2"

    monkeypatch.setattr(di, "_run", fake_run)
    with pytest.raises(di.DeviceError, match="Falha ao instalar"):
        await di.simctl_install("AAAA-BOOTED", Path("/tmp/App.app"))


def _async_return(value):
    async def _coro(*_a, **_kw):
        return value

    return _coro()
