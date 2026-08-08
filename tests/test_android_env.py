"""Testes de src/android_env.py — resolução de ANDROID_HOME/JAVA_HOME e
ajuste de PATH. O módulo roda a resolução como efeito colateral da
importação, então os testes exercitam as funções internas diretamente (sem
reimportar o módulo, o que não refletiria mudanças de env em testes)."""
from pathlib import Path

from src import android_env


def test_first_existing_returns_first_path_that_exists(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    missing = tmp_path / "missing"
    assert android_env._first_existing(missing, real) == real


def test_first_existing_returns_none_when_nothing_exists(tmp_path):
    assert android_env._first_existing(None, tmp_path / "nope") is None


def test_prepend_path_adds_new_dir_once(tmp_path, monkeypatch):
    new_dir = tmp_path / "bin"
    new_dir.mkdir()
    monkeypatch.setenv("PATH", "/usr/bin")
    android_env._prepend_path(new_dir)
    assert str(new_dir) in os_environ_path()
    before = os_environ_path()
    android_env._prepend_path(new_dir)  # idempotente — não duplica
    assert os_environ_path().count(str(new_dir)) == 1
    assert os_environ_path() == before


def test_prepend_path_ignores_nonexistent_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    android_env._prepend_path(tmp_path / "does-not-exist")
    assert os_environ_path() == "/usr/bin"


def test_available_reflects_android_home_resolution(monkeypatch):
    monkeypatch.setattr(android_env, "ANDROID_HOME", Path("/tmp"))
    assert android_env.available() is True
    monkeypatch.setattr(android_env, "ANDROID_HOME", None)
    assert android_env.available() is False


def os_environ_path() -> str:
    import os

    return os.environ["PATH"]
