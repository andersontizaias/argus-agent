"""Testes do pipeline de vídeo da exploração mobile (`src.agent.nodes`) —
três problemas reais achados ao vivo tocando/conferindo o vídeo de runs
explore contra apps iOS e Android de verdade:

1. `_remux_faststart`: o átomo `moov` (índice de duração/posição dos
   frames) vem no FIM do .mp4 que `adb screenrecord`/`simctl io
   recordVideo` produzem — sem remuxar pro início, streaming progressivo
   não consegue nem começar a decodar. Sem depender de um `ffmpeg` de
   verdade instalado no runner de CI: a maioria dos testes mocka
   `subprocess.run`, cobrindo só a lógica Python ao redor dele.
2. `_maybe_start_mobile_recording`/`_start_recording_kwargs`: o driver
   XCUITest (iOS) grava em MJPEG por padrão — um codec que NENHUM
   navegador sabe decodificar num `<video>` HTML5, mesmo com o container
   remuxado certinho.
3. `_maybe_rotate_mobile_recording`/`_concat_video_segments`: o driver de
   cada SO tem um teto de gravação contínua (180s Android, 600s iOS) —
   uma exploração mais longa que isso perdia tudo que aconteceu depois,
   silenciosamente (achado ao vivo: uma exploração Android real de
   ~7m30 gerou um vídeo de só 178s). A rotação pára e reinicia a
   gravação antes do teto, salvando cada pedaço em disco; no fim, os
   pedaços são concatenados num vídeo contínuo só."""
import base64
import subprocess

import pytest

from src.agent.nodes import (
    _ANDROID_RECORDING_ROTATE_SECONDS,
    _ANDROID_RECORDING_TIME_LIMIT_SECONDS,
    _IOS_RECORDING_TIME_LIMIT_SECONDS,
    _concat_video_segments,
    _maybe_rotate_mobile_recording,
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
    def __init__(self, stop_return: bytes | str = b"") -> None:
        self.calls: list[dict] = []
        self.stop_calls = 0
        self._stop_return = stop_return

    def start_recording_screen(self, **options):
        self.calls.append(options)

    def stop_recording_screen(self):
        self.stop_calls += 1
        return self._stop_return


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


async def test_maybe_rotate_mobile_recording_skips_when_not_started(tmp_path):
    driver = _FakeRecordingDriver()
    resources = _RunResources()
    resources.mobile_session = _mobile_session(driver, tmp_path, "android")
    resources.mobile_recording_started = False

    await _maybe_rotate_mobile_recording(resources, "run-1")

    assert driver.stop_calls == 0
    assert resources.mobile_recording_segments == []


async def test_maybe_rotate_mobile_recording_does_nothing_before_the_threshold(tmp_path, monkeypatch):
    driver = _FakeRecordingDriver()
    resources = _RunResources()
    resources.mobile_session = _mobile_session(driver, tmp_path, "android")
    resources.mobile_recording_started = True
    resources.mobile_recording_started_at = 1000.0
    monkeypatch.setattr("time.monotonic", lambda: 1000.0 + _ANDROID_RECORDING_ROTATE_SECONDS - 1)

    await _maybe_rotate_mobile_recording(resources, "run-1")

    assert driver.stop_calls == 0
    assert resources.mobile_recording_segments == []


async def test_maybe_rotate_mobile_recording_rotates_after_the_threshold(tmp_path, monkeypatch):
    # Regressão (achada ao vivo, Android): sem rotação, uma exploração mais
    # longa que o teto de gravação contínua do driver perdia tudo que
    # aconteceu depois dele, sem erro nenhum. Confere que a rotação PARA a
    # gravação atual, salva o pedaço em disco, e começa uma NOVA gravação
    # com os mesmos kwargs de sempre (mesmo codec — pré-requisito pra
    # `_concat_video_segments` poder juntar tudo depois com `-c copy`).
    driver = _FakeRecordingDriver(stop_return=base64.b64encode(b"conteudo-do-primeiro-segmento"))
    resources = _RunResources()
    resources.mobile_session = _mobile_session(driver, tmp_path, "android")
    resources.mobile_recording_started = True
    resources.mobile_recording_started_at = 1000.0
    rotate_time = 1000.0 + _ANDROID_RECORDING_ROTATE_SECONDS + 1
    monkeypatch.setattr("time.monotonic", lambda: rotate_time)

    await _maybe_rotate_mobile_recording(resources, "run-1")

    assert driver.stop_calls == 1
    assert len(resources.mobile_recording_segments) == 1
    segment = resources.mobile_recording_segments[0]
    assert segment.name == "segmento_00.mp4"
    assert segment.read_bytes() == b"conteudo-do-primeiro-segmento"
    # reiniciou a gravação com os mesmos kwargs de sempre (mesmo teto/codec)
    assert driver.calls == [{"timeLimit": _ANDROID_RECORDING_TIME_LIMIT_SECONDS}]
    # e resetou o relógio de rotação a partir de agora
    assert resources.mobile_recording_started_at == rotate_time


async def test_maybe_rotate_mobile_recording_appends_further_segments(tmp_path, monkeypatch):
    driver = _FakeRecordingDriver(stop_return=base64.b64encode(b"segundo-pedaco"))
    resources = _RunResources()
    resources.mobile_session = _mobile_session(driver, tmp_path, "android")
    resources.mobile_recording_started = True
    resources.mobile_recording_started_at = 0.0
    # já tinha um segmento anterior de uma rotação passada
    existing_segment = tmp_path / "video" / "segmento_00.mp4"
    existing_segment.parent.mkdir(parents=True)
    existing_segment.write_bytes(b"primeiro-pedaco")
    resources.mobile_recording_segments = [existing_segment]
    monkeypatch.setattr("time.monotonic", lambda: _ANDROID_RECORDING_ROTATE_SECONDS + 1)

    await _maybe_rotate_mobile_recording(resources, "run-1")

    assert [s.name for s in resources.mobile_recording_segments] == ["segmento_00.mp4", "segmento_01.mp4"]
    assert resources.mobile_recording_segments[1].read_bytes() == b"segundo-pedaco"


async def test_maybe_rotate_mobile_recording_failure_is_best_effort(tmp_path, monkeypatch):
    class _FailingStopDriver:
        def stop_recording_screen(self):
            raise RuntimeError("boom")

    resources = _RunResources()
    resources.mobile_session = _mobile_session(_FailingStopDriver(), tmp_path, "android")
    resources.mobile_recording_started = True
    resources.mobile_recording_started_at = 0.0
    monkeypatch.setattr("time.monotonic", lambda: _ANDROID_RECORDING_ROTATE_SECONDS + 1)

    await _maybe_rotate_mobile_recording(resources, "run-1")  # não deve levantar

    assert resources.mobile_recording_segments == []


def test_concat_single_segment_just_renames_without_calling_ffmpeg(tmp_path, monkeypatch):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("ffmpeg não deveria ser chamado pra um único segmento")

    monkeypatch.setattr("subprocess.run", _fail_if_called)
    segment = tmp_path / "segmento_00.mp4"
    segment.write_bytes(b"conteudo-unico")
    output = tmp_path / "exploracao.mp4"

    _concat_video_segments([segment], output)

    assert output.read_bytes() == b"conteudo-unico"
    assert not segment.exists()


def test_concat_multiple_segments_without_ffmpeg_keeps_only_the_first(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    seg0, seg1 = tmp_path / "segmento_00.mp4", tmp_path / "segmento_01.mp4"
    seg0.write_bytes(b"primeiro")
    seg1.write_bytes(b"segundo")
    output = tmp_path / "exploracao.mp4"

    _concat_video_segments([seg0, seg1], output)

    assert output.read_bytes() == b"primeiro"
    assert not seg1.exists()


def test_concat_multiple_segments_success_removes_the_originals(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    seg0, seg1 = tmp_path / "segmento_00.mp4", tmp_path / "segmento_01.mp4"
    seg0.write_bytes(b"primeiro")
    seg1.write_bytes(b"segundo")
    output = tmp_path / "exploracao.mp4"

    def _fake_run(cmd, **kwargs):
        # ffmpeg de verdade leria a lista de segmentos e escreveria o
        # output — o fake só precisa CRIAR esse arquivo, pra provar que a
        # função segue em frente (limpa os originais) depois da chamada.
        with open(cmd[-1], "wb") as f:
            f.write(b"concatenado")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("subprocess.run", _fake_run)

    _concat_video_segments([seg0, seg1], output)

    assert output.read_bytes() == b"concatenado"
    assert not seg0.exists()
    assert not seg1.exists()
    assert not output.with_suffix(".concat.txt").exists()


def test_concat_multiple_segments_ffmpeg_failure_keeps_only_the_first(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    seg0, seg1 = tmp_path / "segmento_00.mp4", tmp_path / "segmento_01.mp4"
    seg0.write_bytes(b"primeiro")
    seg1.write_bytes(b"segundo")
    output = tmp_path / "exploracao.mp4"

    def _fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr("subprocess.run", _fake_run)

    _concat_video_segments([seg0, seg1], output)

    assert output.read_bytes() == b"primeiro"
    assert not seg1.exists()


@pytest.mark.skipif(
    __import__("shutil").which("ffmpeg") is None,
    reason="requer ffmpeg instalado — pula em ambientes sem ele (ex.: alguns runners de CI)",
)
def test_concat_real_ffmpeg_produces_one_continuous_video(tmp_path):
    """Única checagem end-to-end com o binário de verdade: gera dois .mp4
    de ~1s cada (cores diferentes, mesmo codec/parâmetros — igual sairiam
    de duas chamadas seguidas de `start_recording_screen`) e confere que a
    concatenação produz um vídeo com a duração combinada, não só a do
    primeiro segmento."""
    segments = []
    for index, color in enumerate(("red", "blue")):
        segment = tmp_path / f"segmento_{index:02d}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=64x64:d=1", "-r", "10", str(segment)],
            capture_output=True,
            timeout=30,
            check=True,
        )
        segments.append(segment)
    output = tmp_path / "exploracao.mp4"

    _concat_video_segments(segments, output)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(output)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    duration = float(probe.stdout.strip())
    assert duration >= 1.8, f"esperava ~2s combinados (1s por segmento), veio {duration}s"
