"""
Argus Agent — Secrets Encryption at Rest

Chaves de provider LLM e credenciais de auth para baixar binários mobile são
Fernet-cifradas antes de ir para a tabela `secrets` (src/models.py). A chave
mestra vive só em uma variável de ambiente — nunca no banco, nunca no git.

Gere uma com:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import os

from cryptography.fernet import Fernet, InvalidToken


class MissingSecretKeyError(RuntimeError):
    """ARGUS_SECRET_KEY não está setada — recusa ler/escrever secrets em vez de falhar silenciosamente."""


class SecretDecryptionError(RuntimeError):
    """Ciphertext não pôde ser decriptado — quase sempre um ARGUS_SECRET_KEY diferente do que cifrou."""


def _fernet() -> Fernet:
    key = os.getenv("ARGUS_SECRET_KEY")
    if not key:
        raise MissingSecretKeyError(
            "ARGUS_SECRET_KEY não configurada. Gere uma com: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" '
            "e adicione ao .env."
        )
    try:
        return Fernet(key.encode())
    except ValueError as e:
        raise MissingSecretKeyError(f"ARGUS_SECRET_KEY inválida: {e}") from e


def encrypt_secret(plaintext: str) -> str:
    """Cifra um valor para armazenamento. Vazio permanece vazio (nada a proteger)."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decifra um secret armazenado. Vazio permanece vazio."""
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise SecretDecryptionError(
            "Não foi possível decriptar um secret — ARGUS_SECRET_KEY provavelmente mudou "
            "desde que o valor foi salvo."
        ) from e
