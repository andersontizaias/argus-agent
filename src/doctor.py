"""Argus Agent — "doctor": checagem do ambiente nativo (Playwright, Android,
iOS, Appium, banco, disco). Usado tanto por `GET /api/health` quanto pelo CLI
`argus-doctor` no fim do bootstrap.sh — mesma lógica, duas superfícies."""
import shutil
import subprocess
from dataclasses import dataclass

import sqlalchemy

from src import (  # noqa: F401 — import ajusta PATH/env pro Android SDK (efeito colateral)
    android_env,
    db,
)
from src.settings import artifacts_dir


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _check_db() -> CheckResult:
    try:
        with db.session_scope() as session:
            session.execute(sqlalchemy.text("SELECT 1"))
        return CheckResult("database", True, "SQLite ok")
    except Exception as e:
        return CheckResult("database", False, str(e))


def _check_disk() -> CheckResult:
    try:
        usage = shutil.disk_usage(artifacts_dir())
        free_gb = usage.free / (1024**3)
        ok = free_gb > 2.0
        return CheckResult("disk", ok, f"{free_gb:.1f} GB livres em {artifacts_dir()}")
    except Exception as e:
        return CheckResult("disk", False, str(e))


def _check_binary(name: str, version_args: list[str] | None = None) -> CheckResult:
    path = shutil.which(name)
    if not path:
        return CheckResult(name, False, "não encontrado no PATH")
    if not version_args:
        return CheckResult(name, True, path)
    try:
        out = subprocess.run([name, *version_args], capture_output=True, text=True, timeout=5, check=False)
        version = (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else path
        return CheckResult(name, True, version)
    except Exception:
        return CheckResult(name, True, path)


def _check_playwright() -> CheckResult:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return CheckResult("playwright", True, "Chromium ok")
    except Exception as e:
        return CheckResult("playwright", False, f"{e!s} — rode `uv run playwright install chromium`")


def run_checks() -> list[CheckResult]:
    return [
        _check_db(),
        _check_disk(),
        _check_playwright(),
        _check_binary("adb", ["version"]),
        _check_binary("emulator", ["-version"]),
        _check_binary("xcrun", None),
        _check_binary("appium", ["--version"]),
    ]


def start() -> None:
    """CLI entrypoint: `uv run argus-doctor`."""
    results = run_checks()
    width = max(len(r.name) for r in results)
    for r in results:
        status = "✓" if r.ok else "✗"
        print(f"[{status}] {r.name.ljust(width)}  {r.detail}")
    if not all(r.ok for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    start()
