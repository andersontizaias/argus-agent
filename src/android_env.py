"""Argus Agent — localiza o Android SDK e o JDK nativos do host (instalados
pelo Android Studio, não pelo Argus) e ajusta PATH/env do processo pra
`adb`/`emulator` (e o `appium` global, cujo driver uiautomator2 precisa de
JAVA_HOME) serem resolvíveis — mesmo que o shell que iniciou `argus`/
`argus-worker` não tenha ANDROID_HOME/JAVA_HOME exportados, comum quando o
dev só usa a GUI do Android Studio e nunca mexeu no `.zshrc`. Roda uma vez,
como efeito colateral da importação (mesmo padrão de `load_dotenv()` em
settings.py) — importado cedo por main.py/worker.py/doctor.py, então
qualquer subprocess (`adb`, `emulator`) lançado depois já enxerga o PATH
ajustado."""
import os
from pathlib import Path


def _first_existing(*candidates: Path | None) -> Path | None:
    for c in candidates:
        if c and c.exists():
            return c
    return None


def _resolve_android_home() -> Path | None:
    explicit = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")
    return _first_existing(
        Path(explicit).expanduser() if explicit else None,
        Path.home() / "Library" / "Android" / "sdk",
    )


def _resolve_java_home() -> Path | None:
    explicit = os.getenv("JAVA_HOME")
    return _first_existing(
        Path(explicit).expanduser() if explicit else None,
        # JBR embutido do Android Studio — evita depender de um JDK à parte
        # só pro driver uiautomator2 do Appium (que roda um servidor Java
        # dentro do dispositivo, mas o client precisa de JAVA_HOME válido
        # pra algumas operações do próprio Appium).
        Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home"),
    )


def _prepend_path(*dirs: Path) -> None:
    existing = os.environ.get("PATH", "")
    new_dirs = [str(d) for d in dirs if d.exists() and str(d) not in existing]
    if new_dirs:
        os.environ["PATH"] = os.pathsep.join([*new_dirs, existing])


ANDROID_HOME = _resolve_android_home()
JAVA_HOME = _resolve_java_home()

if ANDROID_HOME:
    os.environ.setdefault("ANDROID_HOME", str(ANDROID_HOME))
    os.environ.setdefault("ANDROID_SDK_ROOT", str(ANDROID_HOME))
    _prepend_path(
        ANDROID_HOME / "platform-tools",
        ANDROID_HOME / "emulator",
        ANDROID_HOME / "cmdline-tools" / "latest" / "bin",
    )

if JAVA_HOME:
    os.environ.setdefault("JAVA_HOME", str(JAVA_HOME))
    _prepend_path(JAVA_HOME / "bin")


def available() -> bool:
    """Usado por device_android.py pra dar um erro claro e cedo (antes de
    tentar rodar `emulator`/`adb`) em vez de deixar o subprocess falhar com
    um genérico "command not found"."""
    return ANDROID_HOME is not None
