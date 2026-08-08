"""Argus Agent — gestão de dispositivo iOS (simulador via `simctl` +
instalação de `.app`). NÃO exposto ao LLM como tool — nós determinísticos
chamados por `provision_target`/`teardown_target`, mesma lógica de
`device_android.py` pro lado Android (essa fase só suporta SIMULADOR, nunca
dispositivo físico — ver `binary_fetch.validate_simulator_app`)."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BOOT_TIMEOUT_SECONDS = 120
# Folga depois do simulador reportar "Booted": o SpringBoard (home screen)
# ainda está assentando por um instante — instalar/lançar um app cedo demais
# nessa janela falha de forma intermitente e confusa.
_POST_BOOT_SETTLE_SECONDS = 3


class DeviceError(RuntimeError):
    """Falha de provisionamento do dispositivo — o chamador deve mapear pra
    status `error` da run (nenhum cenário chegou a rodar)."""


@dataclass
class SimulatorHandle:
    device_name: str
    udid: str


async def _run(*args: str, timeout: float = 30.0) -> str:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError as e:
        proc.kill()
        raise DeviceError(f"Comando `{' '.join(args)}` não respondeu em {timeout}s.") from e
    return stdout.decode(errors="replace")


async def _list_devices_json() -> dict:
    try:
        out = await _run("xcrun", "simctl", "list", "devices", "-j", timeout=15.0)
    except FileNotFoundError as e:
        raise DeviceError("`xcrun`/`simctl` não encontrado — precisa do Xcode instalado.") from e
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise DeviceError(f"Saída inesperada de `simctl list devices -j`: {out[:200]}") from e


async def find_simulator(device_name: str) -> str:
    """Resolve um nome de simulador (ex.: "iPhone 15") pro UDID — se houver
    mais de uma versão de iOS instalada com o mesmo nome de aparelho, pega a
    runtime mais recente (ordenação lexicográfica do nome da runtime, que
    embute a versão)."""
    data = await _list_devices_json()
    candidates: list[tuple[str, str]] = []
    for runtime, devices in data.get("devices", {}).items():
        if "iOS" not in runtime:
            continue
        for d in devices:
            if d.get("name") == device_name and d.get("isAvailable", True):
                candidates.append((runtime, d["udid"]))
    if not candidates:
        raise DeviceError(
            f"Simulador '{device_name}' não encontrado (ou nenhuma versão de iOS instalada tem esse "
            "aparelho disponível). Crie um pelo Xcode: Window > Devices and Simulators."
        )
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


async def _simulator_state(udid: str) -> str | None:
    data = await _list_devices_json()
    for devices in data.get("devices", {}).values():
        for d in devices:
            if d.get("udid") == udid:
                return str(d.get("state"))
    return None


async def is_alive(udid: str) -> bool:
    """Health-check antes de reusar um simulador deixado de pé de uma run
    anterior — mesma mitigação do risco "emuladores/simuladores frágeis" do
    PLANO.md aplicada ao lado iOS."""
    try:
        return await _simulator_state(udid) == "Booted"
    except Exception:
        return False


async def _wait_for_boot(udid: str, *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not await is_alive(udid):
        if time.monotonic() > deadline:
            raise DeviceError(f"Simulador {udid} não terminou de bootar em {timeout_seconds}s.")
        await asyncio.sleep(2)
    await asyncio.sleep(_POST_BOOT_SETTLE_SECONDS)


async def boot_simulator(device_name: str, *, boot_timeout_seconds: int = DEFAULT_BOOT_TIMEOUT_SECONDS) -> SimulatorHandle:
    udid = await find_simulator(device_name)
    if await is_alive(udid):
        return SimulatorHandle(device_name=device_name, udid=udid)

    out = await _run("xcrun", "simctl", "boot", udid, timeout=15.0)
    # "Unable to boot device in current state: Booted" é uma corrida benigna
    # (outra coisa já bootou o mesmo simulador entre o is_alive() e aqui) —
    # qualquer outra saída não-vazia é erro de verdade.
    if out.strip() and "current state: Booted" not in out:
        raise DeviceError(f"Falha ao bootar o simulador: {out.strip()}")

    await _wait_for_boot(udid, timeout_seconds=boot_timeout_seconds)
    return SimulatorHandle(device_name=device_name, udid=udid)


async def shutdown_simulator(handle: SimulatorHandle) -> None:
    """Best-effort — teardown nunca deve levantar (mesmo espírito de
    `_safe_close`/`stop_emulator` nos outros dois lados)."""
    try:
        await _run("xcrun", "simctl", "shutdown", handle.udid, timeout=15.0)
    except Exception:
        pass


async def simctl_install(udid: str, app_path: Path) -> None:
    # `simctl install` não imprime nada em sucesso — qualquer saída indica erro.
    out = await _run("xcrun", "simctl", "install", udid, str(app_path), timeout=60.0)
    if out.strip():
        raise DeviceError(f"Falha ao instalar o app no simulador: {out.strip()}")
