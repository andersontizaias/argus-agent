"""Argus Agent — sobe/derruba um servidor Appium dedicado por run (porta
própria — evita que runs mobile concorrentes brigassem pela mesma sessão).
Nó determinístico chamado por `provision_target`/`teardown_target`, nunca
exposto ao LLM: o agente fala com o app já instalado e rodando, via as
tools de `src/tools/mobile.py` (que falam com o *driver* Appium, não com
este processo servidor diretamente)."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import requests

from src import (
    android_env,  # noqa: F401 — Appium roda o driver uiautomator2, que precisa de JAVA_HOME ajustado
)

DEFAULT_START_TIMEOUT_SECONDS = 30


class AppiumError(RuntimeError):
    """Falha ao subir o servidor Appium — o chamador deve mapear pra status
    `error` da run (nenhum cenário chegou a rodar)."""


@dataclass
class AppiumHandle:
    port: int
    process: asyncio.subprocess.Process

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


async def start_appium(port: int, *, start_timeout_seconds: int = DEFAULT_START_TIMEOUT_SECONDS) -> AppiumHandle:
    try:
        process = await asyncio.create_subprocess_exec(
            "appium", "--port", str(port), "--log-level", "error",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError as e:
        raise AppiumError(
            "`appium` não encontrado no PATH — instale com `npm install -g appium` "
            "e o driver com `appium driver install uiautomator2`."
        ) from e

    handle = AppiumHandle(port=port, process=process)
    try:
        await _wait_for_ready(handle, timeout_seconds=start_timeout_seconds)
    except Exception:
        await stop_appium(handle)
        raise
    return handle


async def _wait_for_ready(handle: AppiumHandle, *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if handle.process.returncode is not None:
            raise AppiumError(f"Servidor Appium encerrou sozinho (código {handle.process.returncode}) antes de ficar pronto.")
        if await _is_ready(handle):
            return
        if time.monotonic() > deadline:
            raise AppiumError(f"Servidor Appium não respondeu em {handle.url}/status em {timeout_seconds}s.")
        await asyncio.sleep(1)


async def _is_ready(handle: AppiumHandle) -> bool:
    try:
        response = await asyncio.to_thread(requests.get, f"{handle.url}/status", timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False


async def stop_appium(handle: AppiumHandle) -> None:
    """Best-effort — teardown nunca deve levantar."""
    try:
        if handle.process.returncode is None:
            handle.process.terminate()
            await asyncio.wait_for(handle.process.wait(), timeout=10.0)
    except Exception:
        try:
            handle.process.kill()
        except Exception:
            pass
