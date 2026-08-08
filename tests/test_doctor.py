from src import doctor


def test_run_checks_returns_all_expected_checks():
    results = doctor.run_checks()
    names = {r.name for r in results}
    assert names == {"database", "disk", "playwright", "adb", "emulator", "xcrun", "appium"}


def test_check_binary_not_found(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    result = doctor._check_binary("totally-not-a-real-binary")
    assert result.ok is False
    assert "não encontrado" in result.detail


def test_check_binary_found_without_version_args(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/xcrun")
    result = doctor._check_binary("xcrun", None)
    assert result.ok is True
    assert result.detail == "/usr/bin/xcrun"


def test_check_binary_version_command_failure_still_ok(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/local/bin/adb")

    def _raise(*_args, **_kwargs):
        raise TimeoutError("boom")

    monkeypatch.setattr(doctor.subprocess, "run", _raise)
    result = doctor._check_binary("adb", ["version"])
    assert result.ok is True
    assert result.detail == "/usr/local/bin/adb"


def test_check_db_failure(monkeypatch):
    def _broken_session_scope():
        raise RuntimeError("db down")

    monkeypatch.setattr(doctor.db, "session_scope", _broken_session_scope)
    result = doctor._check_db()
    assert result.ok is False
    assert "db down" in result.detail


def test_check_disk_failure(monkeypatch):
    def _broken_disk_usage(_path):
        raise OSError("no such path")

    monkeypatch.setattr(doctor.shutil, "disk_usage", _broken_disk_usage)
    result = doctor._check_disk()
    assert result.ok is False


def test_start_exits_nonzero_when_a_check_fails(monkeypatch, capsys):
    import pytest

    from src.doctor import CheckResult

    monkeypatch.setattr(doctor, "run_checks", lambda: [CheckResult("fake", False, "nope")])
    with pytest.raises(SystemExit) as exc_info:
        doctor.start()
    assert exc_info.value.code == 1
    assert "fake" in capsys.readouterr().out


def test_start_no_exit_when_all_checks_pass(monkeypatch, capsys):
    from src.doctor import CheckResult

    monkeypatch.setattr(doctor, "run_checks", lambda: [CheckResult("fake", True, "ok")])
    doctor.start()
    assert "fake" in capsys.readouterr().out
