"""Argus Agent — baixa o binário do app (.apk Android; .zip com .app iOS numa
fase futura) a partir da `binary_url` da run, com autenticação opcional via
secret (`binary_auth_secret` guarda só o NOME do secret, nunca o valor — o
valor nunca aparece em claro na run/nos logs). Usado só por
`provision_target` (nó determinístico do grafo), nunca exposto ao LLM."""
from __future__ import annotations

import asyncio
from pathlib import Path

import requests

from src.user_secrets import get_secret_plain

_APK_MAGIC = b"PK\x03\x04"  # todo .apk é um .zip — assinatura do header local de um zip


class BinaryFetchError(RuntimeError):
    """Falha de provisionamento (download ou validação do binário) — o
    chamador deve mapear pra status `error` da run, não `failed`, já que
    nenhum cenário chegou a rodar."""


async def fetch_binary(url: str, auth_secret_name: str | None, dest_path: Path, *, timeout_seconds: int = 120) -> Path:
    """Baixa `url` pra `dest_path`. Roda a chamada síncrona do `requests` numa
    thread (padrão já usado em routers/config.py pra chamadas bloqueantes
    dentro de handlers async) em vez de puxar uma dependência nova (httpx)
    só pra isso."""
    headers = {}
    if auth_secret_name:
        token = get_secret_plain(auth_secret_name)
        if not token:
            raise BinaryFetchError(f"Secret de autenticação '{auth_secret_name}' não encontrado ou vazio.")
        headers["Authorization"] = token if token.lower().startswith(("bearer ", "basic ")) else f"Bearer {token}"

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    def _download() -> None:
        try:
            with requests.get(url, headers=headers, stream=True, timeout=timeout_seconds) as response:
                if response.status_code >= 400:
                    raise BinaryFetchError(f"Download do binário falhou: HTTP {response.status_code} em {url}")
                with open(dest_path, "wb") as f:
                    f.writelines(response.iter_content(chunk_size=1 << 16))
        except requests.RequestException as e:
            raise BinaryFetchError(f"Erro de rede ao baixar o binário: {e}") from e

    await asyncio.to_thread(_download)

    if not dest_path.exists() or dest_path.stat().st_size == 0:
        raise BinaryFetchError(f"Binário baixado de {url} está vazio.")
    return dest_path


def validate_apk(path: Path) -> None:
    """Confere que o arquivo baixado é mesmo um .apk (zip) antes de tentar
    instalar — um link quebrado costuma devolver uma página HTML de erro com
    HTTP 200 (ex.: login expirado num artifact store), o que passaria batido
    sem essa checagem e só falharia depois, de forma confusa, dentro do
    `adb install`."""
    with open(path, "rb") as f:
        head = f.read(4)
    if head != _APK_MAGIC:
        raise BinaryFetchError(
            "O arquivo baixado não parece ser um .apk válido (não é um .zip) — confira a binary_url e o binary_auth_secret da run."
        )
