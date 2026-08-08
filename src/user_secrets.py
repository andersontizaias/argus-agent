"""Argus Agent — ponte entre `store.secrets` (cifrado) e o resto da app (em claro).

Mantém `src.crypto` isolado do resto do código: quem precisa de um secret em
texto puro chama daqui, nunca decripta na mão."""
from src import crypto, store

# Nomes de secret reconhecidos — chaves de provider LLM + credenciais de
# fontes de binário mobile (uma por nome de secret referenciado em
# `runs.binary_auth_secret`, que pode ser qualquer nome cadastrado).
LLM_SECRET_NAMES = ("anthropic_api_key", "openai_api_key", "gemini_api_key", "groq_api_key",
                    "ollama_api_key", "custom_llm_api_key")


def get_secret_plain(name: str) -> str:
    ciphertext = store.get_secret(name)
    if not ciphertext:
        return ""
    return crypto.decrypt_secret(ciphertext)


def set_secret_plain(name: str, plaintext: str) -> None:
    store.set_secret(name, crypto.encrypt_secret(plaintext) if plaintext else "")
