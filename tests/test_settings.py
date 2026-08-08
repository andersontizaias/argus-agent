import pytest

from src.settings import _env_flag


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
