import pytest

from src.settings import VERSION, _env_flag, _read_version


@pytest.mark.parametrize("value,expected", [
    ("1", True),
    ("true", True),
    ("True", True),
    ("TRUE", True),
    ("yes", True),
    ("on", True),
    ("0", False),
    ("false", False),
    ("no", False),
    ("off", False),
    ("", False),
    ("garbage", False),
])
def test_env_flag_parses_common_truthy_variants(monkeypatch, value, expected):
    monkeypatch.setenv("ARGUS_TEST_FLAG", value)
    assert _env_flag("ARGUS_TEST_FLAG") is expected


def test_env_flag_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("ARGUS_TEST_FLAG", raising=False)
    assert _env_flag("ARGUS_TEST_FLAG") is False
    assert _env_flag("ARGUS_TEST_FLAG", default=True) is True


def test_env_flag_strips_whitespace(monkeypatch):
    monkeypatch.setenv("ARGUS_TEST_FLAG", "  true  ")
    assert _env_flag("ARGUS_TEST_FLAG") is True


def test_version_matches_pyproject_source_of_truth():
    # Não lê o pyproject.toml direto (isso é papel do build) — só garante
    # que veio de algum lugar real via importlib.metadata, não hardcoded.
    assert VERSION == _read_version()
    assert VERSION.count(".") >= 2  # formato semver, ex.: "0.1.0"


def test_read_version_falls_back_when_package_not_found(monkeypatch):
    def _raise(_name):
        from importlib.metadata import PackageNotFoundError
        raise PackageNotFoundError

    monkeypatch.setattr("src.settings.version", _raise)
    assert _read_version() == "0.0.0-dev"
