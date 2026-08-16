"""Testes de `src.agent.nodes._remux_faststart` — o passo que corrige o
`moov` atom no fim do .mp4 que `adb screenrecord`/`simctl io recordVideo`
produzem (achado ao vivo: o `<video>` do browser fica preso em "carregando"
pra sempre com um arquivo assim, mesmo o endpoint de evidência suportando
Range corretamente — o problema é o container, não a entrega HTTP).

Sem depender de um `ffmpeg` de verdade instalado no runner de CI: os
testes mockam `subprocess.run`, cobrindo só a lógica Python ao redor dele
(ausência do binário, falha da chamada, sucesso substituindo o arquivo)."""
import subprocess

import pytest

from src.agent.nodes import _remux_faststart


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
