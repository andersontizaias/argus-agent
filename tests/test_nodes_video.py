"""Testes do pipeline de vídeo da exploração mobile (`src.agent.nodes`) —
dois problemas reais achados ao vivo tocando o vídeo de uma run explore
contra um app iOS de verdade, ambos fazendo o `<video>` do browser ficar
preso em "carregando" pra sempre:

1. `_remux_faststart`: o átomo `moov` (índice de duração/posição dos
   frames) vem no FIM do .mp4 que `adb screenrecord`/`simctl io
   recordVideo` produzem — sem remuxar pro início, streaming progressivo
   não consegue nem começar a decodar. Sem depender de um `ffmpeg` de
   verdade instalado no runner de CI: a maioria dos testes mocka
   `subprocess.run`, cobrindo só a lógica Python ao redor dele.
2. `_maybe_start_mobile_recording`: o driver XCUITest (iOS) grava em
   MJPEG por padrão — um codec que NENHUM navegador sabe decodificar num
   `<video>` HTML5, mesmo com o container remuxado certinho."""
import subprocess

import pytest

from src.agent.nodes import (
    _ANDROID_RECORDING_TIME_LIMIT_SECONDS,
    _IOS_RECORDING_TIME_LIMIT_SECONDS,
    _maybe_start_mobile_recording,
    _remux_faststart,
    _RunResources,
)
from src.tools.mobile import MobileSession

pytestmark = pytest.mark.anyio


def test_remux_skips_when_ffmpeg_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    video = tmp_path / "exploracao.mp4"
    video.write_bytes(b"conteudo-original")

    _remux_faststart(video)

    # Sem ffmpeg, mantém o arquivo cru intocado — a evidência ainda fica
    # salva e baixável, só não toca via streaming direto no navegador.
    assert video.read_bytes() == b"conteudo-original"


def test_remux_keeps_original_file_when_ffmpeg_call_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")

    def _fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr("subprocess.run", _fake_run)
    video = tmp_path / "exploracao.mp4"
    video.write_bytes(b"conteudo-original")

    _remux_faststart(video)

    assert video.read_bytes() == b"conteudo-original"
    # Não deixa lixo pra trás — o .faststart.mp4 temporário é removido no
    # caminho de erro.
    assert not (tmp_path / "exploracao.faststart.mp4").exists()


def test_remux_replaces_original_with_remuxed_output_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    video = tmp_path / "exploracao.mp4"
    video.write_bytes(b"conteudo-original")

    def _fake_run(cmd, **kwargs):
        # ffmpeg de verdade escreveria o remux no penúltimo argumento (o
        # output path) — o fake só precisa CRIAR esse arquivo pra provar
        # que `_remux_faststart` faz `tmp_path.replace(path)` em seguida.
        output_path = cmd[-1]
        with open(output_path, "wb") as f:
            f.write(b"conteudo-remuxado")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("subprocess.run", _fake_run)

    _remux_faststart(video)

    assert video.read_bytes() == b"conteudo-remuxado"
    assert not (tmp_path / "exploracao.faststart.mp4").exists()


def test_remux_timeout_keeps_original_file(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")

    def _fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 60))

    monkeypatch.setattr("subprocess.run", _fake_run)
    video = tmp_path / "exploracao.mp4"
    video.write_bytes(b"conteudo-original")

    _remux_faststart(video)

    assert video.read_bytes() == b"conteudo-original"


@pytest.mark.skipif(
    __import__("shutil").which("ffmpeg") is None,
    reason="requer ffmpeg instalado — pula em ambientes sem ele (ex.: alguns runners de CI)",
)
def test_remux_real_ffmpeg_moves_moov_atom_to_the_front(tmp_path):
    """Única checagem end-to-end com o binário de verdade: gera um .mp4
    minúsculo (1 frame, cor sólida) via ffmpeg — que por padrão já escreve
    `moov` perto do fim pra um arquivo tocável localmente, mas confirma que
    depois do remux ele fica ANTES do `mdat` (o que importa pra streaming
    progressivo, ver docstring de `_remux_faststart`)."""
    src = tmp_path / "gerado.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-frames:v", "1", str(src)],
        capture_output=True,
        timeout=30,
        check=True,
    )

    _remux_faststart(src)

    data = src.read_bytes()
    moov_idx = data.find(b"moov")
    mdat_idx = data.find(b"mdat")
    assert moov_idx != -1 and mdat_idx != -1
    assert moov_idx < mdat_idx, "moov deveria vir antes de mdat depois do remux 'faststart'"


class _FakeRecordingDriver:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def start_recording_screen(self, **options):
        self.calls.append(options)


class _FailingRecordingDriver:
    def start_recording_screen(self, **options):
        raise RuntimeError("boom")


def _mobile_session(driver, tmp_path, platform):
    return MobileSession(driver=driver, app_package="com.example.app", run_id="run-1", artifacts_dir=tmp_path, platform=platform)


async def test_maybe_start_mobile_recording_forces_h264_on_ios(tmp_path):
    # Regressão: o driver XCUITest grava em MJPEG por padrão — nenhum
    # navegador sabe decodificar isso num <video> HTML5, mesmo com o
    # container remuxado certinho (ver docstring do módulo).
    driver = _FakeRecordingDriver()
    resources = _RunResources()
    resources.mobile_session = _mobile_session(driver, tmp_path, "ios")

    await _maybe_start_mobile_recording(resources, "run-1")

    assert resources.mobile_recording_started is True
    assert driver.calls == [
        {"videoType": "libx264", "pixelFormat": "yuv420p", "timeLimit": _IOS_RECORDING_TIME_LIMIT_SECONDS}
    ]


async def test_maybe_start_mobile_recording_uses_max_time_limit_on_android(tmp_path):
    # Android (`adb screenrecord`) já grava em H.264 nativamente — não tem
    # (nem precisa) da opção `videoType`. `timeLimit` é forçado pro máximo
    # que o driver aceita (180s — teto do próprio `adb screenrecord`).
    driver = _FakeRecordingDriver()
    resources = _RunResources()
    resources.mobile_session = _mobile_session(driver, tmp_path, "android")

    await _maybe_start_mobile_recording(resources, "run-1")

    assert resources.mobile_recording_started is True
    assert driver.calls == [{"timeLimit": _ANDROID_RECORDING_TIME_LIMIT_SECONDS}]


async def test_maybe_start_mobile_recording_failure_is_best_effort(tmp_path):
    resources = _RunResources()
    resources.mobile_session = _mobile_session(_FailingRecordingDriver(), tmp_path, "ios")

    await _maybe_start_mobile_recording(resources, "run-1")  # não deve levantar

    assert resources.mobile_recording_started is False
