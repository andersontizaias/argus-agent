from src import store


def test_secret_set_get_roundtrip():
    store.set_secret("anthropic_api_key", "enc-value")
    assert store.get_secret("anthropic_api_key") == "enc-value"


def test_secret_missing_returns_none():
    assert store.get_secret("nonexistent") is None


def test_secret_empty_value_deletes_row():
    store.set_secret("openai_api_key", "enc-value")
    store.set_secret("openai_api_key", "")
    assert store.get_secret("openai_api_key") is None


def test_secret_update_existing_row():
    store.set_secret("groq_api_key", "v1")
    store.set_secret("groq_api_key", "v2")
    assert store.get_secret("groq_api_key") == "v2"


def test_list_secret_names_sorted():
    store.set_secret("z_key", "v")
    store.set_secret("a_key", "v")
    names = store.list_secret_names()
    assert names == sorted(names)
    assert "a_key" in names and "z_key" in names


def test_setting_default_when_missing():
    assert store.get_setting("missing_key", "fallback") == "fallback"
    assert store.get_setting("missing_key") == ""


def test_setting_set_and_update():
    store.set_setting("default_llm_provider", "anthropic")
    assert store.get_setting("default_llm_provider") == "anthropic"
    store.set_setting("default_llm_provider", "openai")
    assert store.get_setting("default_llm_provider") == "openai"


def test_create_and_verify_api_key():
    row, full_key = store.create_api_key("ci-token")
    assert full_key.startswith("argus_")
    assert row.name == "ci-token"

    verified = store.verify_api_key(full_key)
    assert verified is not None
    assert verified.id == row.id
    assert verified.last_used_at is not None


def test_verify_api_key_rejects_wrong_key():
    store.create_api_key("ci-token")
    assert store.verify_api_key("argus_wrong_wrongwrongwrong") is None


def test_verify_api_key_rejects_malformed_key():
    assert store.verify_api_key("not-an-argus-key") is None
    assert store.verify_api_key("argus_onlyoneseparator") is None


def test_verify_api_key_rejects_revoked_key():
    row, full_key = store.create_api_key("ci-token")
    store.revoke_api_key(row.id)
    assert store.verify_api_key(full_key) is None


def test_revoke_api_key_returns_false_for_unknown_id():
    assert store.revoke_api_key("does-not-exist") is False


def test_list_api_keys_ordered_newest_first():
    _row1, _ = store.create_api_key("first")
    row2, _ = store.create_api_key("second")
    keys = store.list_api_keys()
    assert keys[0].id == row2.id
