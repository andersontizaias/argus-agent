"""Argus Agent — ponte entre `store.secrets` (cifrado) e o resto da app (em claro).

Mantém `src.crypto` isolado do resto do código: quem precisa de um secret em
texto puro chama daqui, nunca decripta na mão."""
from typing import TypedDict

from src import crypto, store

# Nomes de secret reconhecidos — chaves de provider LLM + credenciais de
# fontes de binário mobile (uma por nome de secret referenciado em
# `runs.binary_auth_secret`, que pode ser qualquer nome cadastrado).
LLM_SECRET_NAMES = ("anthropic_api_key", "openai_api_key", "gemini_api_key", "groq_api_key",
                    "ollama_api_key", "custom_llm_api_key", "bedrock_api_key",
                    "bedrock_access_key_id", "bedrock_secret_access_key", "bedrock_session_token")


def get_secret_plain(name: str) -> str:
    ciphertext = store.get_secret(name)
    if not ciphertext:
        return ""
    return crypto.decrypt_secret(ciphertext)


def set_secret_plain(name: str, plaintext: str) -> None:
    store.set_secret(name, crypto.encrypt_secret(plaintext) if plaintext else "")


class BedrockSigv4Credentials(TypedDict):
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_session_token: str


# Dict vazio (não um `BedrockSigv4Credentials` incompleto) pro `**extra` dos
# call sites quando o provider não é Bedrock — `build_chat_model` já tem
# default `""` pros 3 kwargs, então não passar nada é equivalente e mantém
# o TypedDict (usado só no caso Bedrock) checável pelo mypy via `**kwargs`.
NO_EXTRA_CREDENTIALS: dict[str, str] = {}


def get_bedrock_sigv4_credentials() -> BedrockSigv4Credentials:
    """As 3 credenciais do modo avançado do Bedrock (SigV4) que
    `build_chat_model` recebe como kwargs nomeados — nenhuma delas é
    `provider.secret_name` (esse é `bedrock_api_key`, o modo padrão), então
    o caller genérico não as busca sozinho. Já em claro — mesma convenção
    de `get_secret_plain`."""
    return {
        "aws_access_key_id": get_secret_plain("bedrock_access_key_id"),
        "aws_secret_access_key": get_secret_plain("bedrock_secret_access_key"),
        "aws_session_token": get_secret_plain("bedrock_session_token"),
    }
