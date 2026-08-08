"""Testes de src/tools/device_android.py — gestão de emulador/instalação via
subprocess, tudo mockado (não depende de Android SDK instalado pra rodar a
suíte; a verificação com emulador de verdade é manual/local, ver PLANO.md)."""
import asyncio
import itertools
from pathlib import Path

import pytest

from src.tools import device_android as da

pytestmark = pytest.mark.anyio


class _FakeProcess:
    def __init__(self):
        self.returncode = None
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

    async def communicate(self):
        return b"", b""


def _async_return(value):
    async def _coro(*_a, **_kw):
        return value

    return _coro()


async def test_list_avds_parses_output(monkeypatch):
    async def fake_run(*_args, **_kw):
        return "Pixel_9a\nMedium_Phone_API_36.1\n"

    monkeypatch.setattr(da, "_run", fake_run)
    assert await da._list_avds() == ["Pixel_9a", "Medium_Phone_API_36.1"]


async def test_list_avds_raises_clear_error_when_emulator_binary_missing(monkeypatch):
    async def fake_run(*_a, **_kw):
        raise FileNotFoundError()

    monkeypatch.setattr(da, "_run", fake_run)
    with pytest.raises(da.DeviceError, match="não encontrado no PATH"):
        await da._list_avds()


async def test_ensure_avd_passes_when_present(monkeypatch):
    monkeypatch.setattr(da, "_list_avds", lambda: _async_return(["Pixel_9a"]))
    await da.ensure_avd("Pixel_9a")  # não levanta


async def test_ensure_avd_raises_with_available_list_when_missing(monkeypatch):
    monkeypatch.setattr(da, "_list_avds", lambda: _async_return(["Pixel_9a"]))
    with pytest.raises(da.DeviceError, match="não encontrado"):
        await da.ensure_avd("Outro_AVD")


async def test_adb_devices_parses_only_ready_devices(monkeypatch):
    output = "List of devices attached\nemulator-5554\tdevice\nemulator-5556\toffline\n"

    async def fake_run(*_a, **_kw):
        return output

    monkeypatch.setattr(da, "_run", fake_run)
    assert await da._adb_devices() == {"emulator-5554"}


async def test_adb_install_success(monkeypatch):
    async def fake_run(*_a, **_kw):
        return "Success\n"

    monkeypatch.setattr(da, "_run", fake_run)
    await da.adb_install("emulator-5554", Path("/tmp/app.apk"))  # não levanta


async def test_adb_install_failure_raises(monkeypatch):
    async def fake_run(*_a, **_kw):
        return "Failure [INSTALL_FAILED_INVALID_APK]\n"

    monkeypatch.setattr(da, "_run", fake_run)
    with pytest.raises(da.DeviceError, match="Falha ao instalar"):
        await da.adb_install("emulator-5554", Path("/tmp/app.apk"))


async def test_is_alive_true_when_device_state(monkeypatch):
    async def fake_run(*_a, **_kw):
        return "device\n"

    monkeypatch.setattr(da, "_run", fake_run)
    handle = da.EmulatorHandle(avd_name="Pixel_9a", port=5554, serial="emulator-5554", process=_FakeProcess())
    assert await da.is_alive(handle) is True


async def test_is_alive_false_on_error(monkeypatch):
    async def fake_run(*_a, **_kw):
        raise da.DeviceError("boom")

    monkeypatch.setattr(da, "_run", fake_run)
    handle = da.EmulatorHandle(avd_name="Pixel_9a", port=5554, serial="emulator-5554", process=_FakeProcess())
    assert await da.is_alive(handle) is False


async def test_boot_emulator_returns_handle_on_success(monkeypatch):
    monkeypatch.setattr(da, "ensure_avd", lambda _name: _async_return(None))

    async def fake_create_subprocess_exec(*_args, **_kw):
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(da, "_wait_for_boot", lambda *_a, **_kw: _async_return(None))

    handle = await da.boot_emulator("Pixel_9a", 5554)
    assert handle.avd_name == "Pixel_9a"
    assert handle.serial == "emulator-5554"


async def test_boot_emulator_stops_emulator_when_boot_fails(monkeypatch):
    monkeypatch.setattr(da, "ensure_avd", lambda _name: _async_return(None))

    async def fake_create_subprocess_exec(*_args, **_kw):
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    async def fake_wait_for_boot(*_a, **_kw):
        raise da.DeviceError("nunca bootou")

    monkeypatch.setattr(da, "_wait_for_boot", fake_wait_for_boot)

    stopped = {}

    async def fake_stop(_handle):
        stopped["called"] = True

    monkeypatch.setattr(da, "stop_emulator", fake_stop)

    with pytest.raises(da.DeviceError, match="nunca bootou"):
        await da.boot_emulator("Pixel_9a", 5554)
    assert stopped.get("called") is True


async def test_stop_emulator_terminates_process(monkeypatch):
    async def fake_run(*_a, **_kw):
        return ""

    monkeypatch.setattr(da, "_run", fake_run)
    process = _FakeProcess()
    handle = da.EmulatorHandle(avd_name="Pixel_9a", port=5554, serial="emulator-5554", process=process)
    await da.stop_emulator(handle)
    assert process.terminated is True


async def test_stop_emulator_never_raises_even_if_adb_kill_fails(monkeypatch):
    async def fake_run(*_a, **_kw):
        raise da.DeviceError("adb sumiu")

    monkeypatch.setattr(da, "_run", fake_run)
    process = _FakeProcess()
    handle = da.EmulatorHandle(avd_name="Pixel_9a", port=5554, serial="emulator-5554", process=process)
    await da.stop_emulator(handle)  # não levanta mesmo com adb falhando


async def test_wait_for_boot_raises_on_device_not_appearing(monkeypatch):
    async def fake_adb_devices():
        return set()

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(da, "_adb_devices", fake_adb_devices)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    # 1ª chamada (deadline) = 0; todas as seguintes já excedem o timeout.
    times = itertools.chain([0], itertools.repeat(1000))
    monkeypatch.setattr(da.time, "monotonic", lambda: next(times))

    with pytest.raises(da.DeviceError, match="não apareceu no `adb devices`"):
        await da._wait_for_boot("emulator-5554", timeout_seconds=5)


async def test_wait_for_boot_raises_when_boot_never_completes(monkeypatch):
    async def fake_adb_devices():
        return {"emulator-5554"}

    async def fake_adb_shell(*_a, **_kw):
        return "0"  # nunca completa

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(da, "_adb_devices", fake_adb_devices)
    monkeypatch.setattr(da, "_adb_shell", fake_adb_shell)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    times = itertools.chain([0], itertools.repeat(1000))
    monkeypatch.setattr(da.time, "monotonic", lambda: next(times))

    with pytest.raises(da.DeviceError, match="não terminou de bootar"):
        await da._wait_for_boot("emulator-5554", timeout_seconds=5)


async def test_wait_for_boot_succeeds_when_boot_completes(monkeypatch):
    async def fake_adb_devices():
        return {"emulator-5554"}

    async def fake_adb_shell(*_a, **_kw):
        return "1"

    monkeypatch.setattr(da, "_adb_devices", fake_adb_devices)
    monkeypatch.setattr(da, "_adb_shell", fake_adb_shell)

    await da._wait_for_boot("emulator-5554", timeout_seconds=5)  # não levanta
