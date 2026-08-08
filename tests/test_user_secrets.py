from src import user_secrets


def test_get_secret_plain_roundtrip():
    user_secrets.set_secret_plain("anthropic_api_key", "sk-ant-plain-value")
    assert user_secrets.get_secret_plain("anthropic_api_key") == "sk-ant-plain-value"


def test_get_secret_plain_missing_returns_empty():
    assert user_secrets.get_secret_plain("never_set") == ""


def test_set_secret_plain_empty_clears():
    user_secrets.set_secret_plain("openai_api_key", "value")
    user_secrets.set_secret_plain("openai_api_key", "")
    assert user_secrets.get_secret_plain("openai_api_key") == ""
