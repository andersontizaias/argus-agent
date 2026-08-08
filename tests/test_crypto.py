import os

import pytest

from src import crypto


def test_encrypt_decrypt_roundtrip():
    ciphertext = crypto.encrypt_secret("sk-ant-abcdefgh12345678")
    assert ciphertext != "sk-ant-abcdefgh12345678"
    assert crypto.decrypt_secret(ciphertext) == "sk-ant-abcdefgh12345678"


def test_encrypt_blank_stays_blank():
    assert crypto.encrypt_secret("") == ""
    assert crypto.decrypt_secret("") == ""


def test_missing_secret_key_raises(monkeypatch):
    monkeypatch.delenv("ARGUS_SECRET_KEY", raising=False)
    with pytest.raises(crypto.MissingSecretKeyError):
        crypto.encrypt_secret("x")


def test_invalid_secret_key_raises(monkeypatch):
    monkeypatch.setenv("ARGUS_SECRET_KEY", "not-a-valid-fernet-key")
    with pytest.raises(crypto.MissingSecretKeyError):
        crypto.encrypt_secret("x")


def test_decrypt_with_wrong_key_raises(monkeypatch):
    ciphertext = crypto.encrypt_secret("secret-value")
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ARGUS_SECRET_KEY", Fernet.generate_key().decode())
    with pytest.raises(crypto.SecretDecryptionError):
        crypto.decrypt_secret(ciphertext)


def test_key_read_from_env_each_call(monkeypatch):
    # garante que _fernet() lê ARGUS_SECRET_KEY do ambiente atual, não de um
    # valor cacheado no import do módulo.
    assert os.environ["ARGUS_SECRET_KEY"]
    ciphertext = crypto.encrypt_secret("value")
    assert crypto.decrypt_secret(ciphertext) == "value"
