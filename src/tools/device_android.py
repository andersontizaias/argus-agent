"""Argus Agent — gestão de dispositivo Android (emulador + instalação de
APK). NÃO exposto ao LLM como tool — são nós determinísticos chamados por
`provision_target`/`teardown_target` (ver src/agent/nodes.py), na mesma
lógica do Playwright `browser.launch()`/`browser.close()` pro caminho web.
O agente só fala com o app já instalado e rodando, via Appium (src/tools/
mobile.py)."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from src import (
    android_env,  # noqa: F401 — garante PATH/env ajustados antes de qualquer subprocess
)

DEFAULT_BOOT_TIMEOUT_SECONDS = 180


class DeviceError(RuntimeError):
    """Falha de provisionamento do dispositivo — o chamador deve mapear pra
    status `error` da run, não `failed` (nenhum cenário chegou a rodar)."""


@dataclass
class EmulatorHandle:
    avd_name: str
    port: int
    serial: str
    process: asyncio.subprocess.Process


async def _run(*args: str, timeout: float = 15.0) -> str:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError as e:
        proc.kill()
        raise DeviceError(f"Comando `{' '.join(args)}` não respondeu em {timeout}s.") from e
    return stdout.decode(errors="replace")


async def _list_avds() -> list[str]:
    try:
        out = await _run("emulator", "-list-avds", timeout=10.0)
    except FileNotFoundError as e:
        raise DeviceError(
            "`emulator` não encontrado no PATH — instale o Android SDK via Android Studio "
            "(ANDROID_HOME esperado em ~/Library/Android/sdk)."
        ) from e
    return [line.strip() for line in out.splitlines() if line.strip()]


async def ensure_avd(avd_name: str) -> None:
    avds = await _list_avds()
    if avd_name not in avds:
        raise DeviceError(
            f"AVD '{avd_name}' não encontrado. Disponíveis: {', '.join(avds) or '(nenhum)'}. "
            "Crie um pelo Device Manager do Android Studio."
        )


async def _adb_devices() -> set[str]:
    out = await _run("adb", "devices")
    serials = set()
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device":
            serials.add(parts[0])
    return serials


async def _adb_shell(serial: str, *args: str, timeout: float = 15.0) -> str:
    return await _run("adb", "-s", serial, "shell", *args, timeout=timeout)


async def _wait_for_boot(serial: str, *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while serial not in await _adb_devices():
        if time.monotonic() > deadline:
            raise DeviceError(f"Emulador {serial} não apareceu no `adb devices` em {timeout_seconds}s.")
        await asyncio.sleep(2)
    while True:
        completed = await _adb_shell(serial, "getprop", "sys.boot_completed")
        if completed.strip() == "1":
            return
        if time.monotonic() > deadline:
            raise DeviceError(f"Emulador {serial} não terminou de bootar em {timeout_seconds}s.")
        await asyncio.sleep(2)


async def is_alive(handle: EmulatorHandle) -> bool:
    """Health-check antes de reusar um emulador deixado de pé de uma run
    anterior (risco #1 do PLANO.md: 'emuladores frágeis' — health-check +
    auto-repair em vez de assumir que continua bom)."""
    try:
        out = await _run("adb", "-s", handle.serial, "get-state", timeout=5.0)
        return out.strip() == "device"
    except Exception:
        return False


async def boot_emulator(avd_name: str, port: int, *, boot_timeout_seconds: int = DEFAULT_BOOT_TIMEOUT_SECONDS) -> EmulatorHandle:
    await ensure_avd(avd_name)
    serial = f"emulator-{port}"
    try:
        process = await asyncio.create_subprocess_exec(
            "emulator", "-avd", avd_name, "-port", str(port),
            "-no-snapshot-save", "-no-boot-anim", "-no-audio",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError as e:
        raise DeviceError("`emulator` não encontrado no PATH.") from e

    handle = EmulatorHandle(avd_name=avd_name, port=port, serial=serial, process=process)
    try:
        await _wait_for_boot(serial, timeout_seconds=boot_timeout_seconds)
    except Exception:
        await stop_emulator(handle)
        raise
    return handle


async def stop_emulator(handle: EmulatorHandle) -> None:
    """Best-effort — teardown nunca deve levantar (mesmo espírito de
    `_safe_close` em nodes.py pro lado web)."""
    try:
        await _run("adb", "-s", handle.serial, "emu", "kill", timeout=10.0)
    except Exception:
        pass
    try:
        if handle.process.returncode is None:
            handle.process.terminate()
            await asyncio.wait_for(handle.process.wait(), timeout=10.0)
    except Exception:
        try:
            handle.process.kill()
        except Exception:
            pass


async def adb_install(serial: str, apk_path: Path) -> None:
    out = await _run("adb", "-s", serial, "install", "-r", str(apk_path), timeout=120.0)
    if "Success" not in out:
        raise DeviceError(f"Falha ao instalar o APK: {out.strip()}")
