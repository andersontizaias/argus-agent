"""Argus Agent — baixa o binário do app (.apk Android; .zip com .app iOS) a
partir da `binary_url` da run, com autenticação opcional via secret
(`binary_auth_secret` guarda só o NOME do secret, nunca o valor — o valor
nunca aparece em claro na run/nos logs). Usado só por `provision_target` (nó
determinístico do grafo), nunca exposto ao LLM."""
from __future__ import annotations

import asyncio
import plistlib
import zipfile
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


def extract_ios_app(zip_path: Path, dest_dir: Path) -> Path:
    """Extrai o .zip da run iOS e localiza o `.app` dentro dele. A Apple usa
    a mesma convenção `Payload/<Nome>.app/` tanto pra `.ipa` de dispositivo
    quanto pra exports de simulador zipados — o zip em si não distingue os
    dois casos, só o conteúdo (ver `validate_simulator_app`)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest_dir)
    except zipfile.BadZipFile as e:
        raise BinaryFetchError(
            "O arquivo baixado não parece ser um .zip válido — confira a binary_url e o binary_auth_secret da run."
        ) from e

    app_dirs = sorted(dest_dir.glob("Payload/*.app")) or sorted(dest_dir.glob("*.app"))
    if not app_dirs:
        raise BinaryFetchError(
            "Não encontrei um .app dentro do .zip — confira se a binary_url aponta pra um export "
            "de simulador (estrutura Payload/<Nome>.app)."
        )
    if len(app_dirs) > 1:
        names = ", ".join(d.name for d in app_dirs)
        raise BinaryFetchError(f"Mais de um .app encontrado no .zip: {names}.")
    return app_dirs[0]


def validate_simulator_app(app_path: Path) -> None:
    """Confirma que o `.app` é um build de SIMULADOR, não de dispositivo
    físico — essa fase só suporta simulador. `CFBundleSupportedPlatforms`
    no Info.plist é o sinal oficial da Apple pra isso ("iPhoneSimulator" vs
    "iPhoneOS"); sem essa checagem, um .ipa de device falharia depois, de
    forma críptica, dentro do `simctl install`."""
    info_plist = app_path / "Info.plist"
    if not info_plist.exists():
        raise BinaryFetchError(f"Info.plist não encontrado em {app_path.name} — build inválido.")
    with open(info_plist, "rb") as f:
        try:
            plist = plistlib.load(f)
        except (plistlib.InvalidFileException, ValueError) as e:
            raise BinaryFetchError(f"Info.plist de {app_path.name} não pôde ser lido: {e}") from e

    platforms = plist.get("CFBundleSupportedPlatforms", [])
    if "iPhoneSimulator" not in platforms:
        raise BinaryFetchError(
            f"'{app_path.name}' não é um build de SIMULADOR (CFBundleSupportedPlatforms={platforms!r}) "
            "— só simulador é suportado por enquanto, nada de dispositivo físico. Exporte um build "
            "\"Any iOS Simulator Device\" no Xcode (Product > Archive > Distribute App > Development, "
            "ou um build de Debug direto pro simulador) e aponte a binary_url pro .zip resultante."
        )


def bundle_id_from_app(app_path: Path) -> str:
    """Lê o `CFBundleIdentifier` do Info.plist — usado pra launch_app/
    terminate_app da run (equivalente ao package name do Android). Extraído
    do build local em vez de perguntado ao driver Appium depois da sessão
    criada: mais direto e não depende de como cada driver expõe isso nas
    capabilities da sessão."""
    info_plist = app_path / "Info.plist"
    with open(info_plist, "rb") as f:
        plist = plistlib.load(f)
    bundle_id = plist.get("CFBundleIdentifier")
    if not bundle_id:
        raise BinaryFetchError(f"CFBundleIdentifier não encontrado em {app_path.name}/Info.plist.")
    return str(bundle_id)
