"""Testes de src/tools/binary_fetch.py — download do binário (mockando
`requests.get`, sem rede de verdade) e validação de assinatura .apk /
extração e validação do .app iOS."""
import plistlib
import zipfile

import pytest

from src.tools import binary_fetch

pytestmark = pytest.mark.anyio


class _FakeResponse:
    def __init__(self, status_code=200, chunks=(b"PK\x03\x04resto-do-apk",)):
        self.status_code = status_code
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_content(self, chunk_size):
        yield from self._chunks


async def test_fetch_binary_downloads_to_dest_path(tmp_path, monkeypatch):
    captured = {}

    def fake_get(url, headers=None, stream=None, timeout=None):
        captured.update(url=url, headers=headers)
        return _FakeResponse()

    monkeypatch.setattr(binary_fetch.requests, "get", fake_get)
    dest = tmp_path / "app.apk"

    result = await binary_fetch.fetch_binary("https://example.com/app.apk", None, dest)

    assert result == dest
    assert dest.read_bytes() == b"PK\x03\x04resto-do-apk"
    assert captured["url"] == "https://example.com/app.apk"
    assert captured["headers"] == {}


async def test_fetch_binary_adds_bearer_auth_header_from_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(binary_fetch, "get_secret_plain", lambda _name: "abc123")
    captured = {}

    def fake_get(url, headers=None, stream=None, timeout=None):
        captured["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(binary_fetch.requests, "get", fake_get)
    await binary_fetch.fetch_binary("https://x/app.apk", "my_secret", tmp_path / "a.apk")

    assert captured["headers"]["Authorization"] == "Bearer abc123"


async def test_fetch_binary_preserves_prefixed_auth_header(tmp_path, monkeypatch):
    # Um secret já vem no formato "Basic xxx" — não deve virar "Bearer Basic xxx".
    monkeypatch.setattr(binary_fetch, "get_secret_plain", lambda _name: "Basic dXNlcjpwYXNz")
    captured = {}

    def fake_get(url, headers=None, stream=None, timeout=None):
        captured["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(binary_fetch.requests, "get", fake_get)
    await binary_fetch.fetch_binary("https://x/app.apk", "my_secret", tmp_path / "a.apk")

    assert captured["headers"]["Authorization"] == "Basic dXNlcjpwYXNz"


async def test_fetch_binary_raises_when_secret_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(binary_fetch, "get_secret_plain", lambda _name: "")
    with pytest.raises(binary_fetch.BinaryFetchError, match="não encontrado ou vazio"):
        await binary_fetch.fetch_binary("https://x/app.apk", "missing_secret", tmp_path / "a.apk")


async def test_fetch_binary_raises_on_http_error_status(tmp_path, monkeypatch):
    monkeypatch.setattr(binary_fetch.requests, "get", lambda *_a, **_kw: _FakeResponse(status_code=404))
    with pytest.raises(binary_fetch.BinaryFetchError, match="HTTP 404"):
        await binary_fetch.fetch_binary("https://x/app.apk", None, tmp_path / "a.apk")


async def test_fetch_binary_raises_on_empty_download(tmp_path, monkeypatch):
    monkeypatch.setattr(binary_fetch.requests, "get", lambda *_a, **_kw: _FakeResponse(chunks=()))
    with pytest.raises(binary_fetch.BinaryFetchError, match="está vazio"):
        await binary_fetch.fetch_binary("https://x/app.apk", None, tmp_path / "a.apk")


async def test_fetch_binary_wraps_network_errors(tmp_path, monkeypatch):
    import requests as requests_module

    def fake_get(*_a, **_kw):
        raise requests_module.ConnectionError("conexão recusada")

    monkeypatch.setattr(binary_fetch.requests, "get", fake_get)
    with pytest.raises(binary_fetch.BinaryFetchError, match="Erro de rede"):
        await binary_fetch.fetch_binary("https://x/app.apk", None, tmp_path / "a.apk")


# ─── binary_url apontando pra um arquivo local (upload ou caminho digitado) ─


async def test_fetch_binary_copies_local_absolute_path_instead_of_downloading(tmp_path, monkeypatch):
    def fail_if_called(*_a, **_kw):
        raise AssertionError("não devia tentar baixar via HTTP pra um caminho local")

    monkeypatch.setattr(binary_fetch.requests, "get", fail_if_called)
    src = tmp_path / "meu-app.apk"
    src.write_bytes(b"conteudo-do-apk-local")
    dest = tmp_path / "run-dir" / "app.apk"

    result = await binary_fetch.fetch_binary(str(src), None, dest)

    assert result == dest
    assert dest.read_bytes() == b"conteudo-do-apk-local"


async def test_fetch_binary_copies_local_file_uri(tmp_path, monkeypatch):
    monkeypatch.setattr(binary_fetch.requests, "get", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("http")))
    src = tmp_path / "meu-app.ipa"
    src.write_bytes(b"conteudo-do-ipa-local")
    dest = tmp_path / "run-dir" / "app.zip"

    result = await binary_fetch.fetch_binary(f"file://{src}", None, dest)

    assert result == dest
    assert dest.read_bytes() == b"conteudo-do-ipa-local"


async def test_fetch_binary_raises_clearly_when_local_path_missing(tmp_path):
    with pytest.raises(binary_fetch.BinaryFetchError, match="não encontrado"):
        await binary_fetch.fetch_binary(str(tmp_path / "nao-existe.apk"), None, tmp_path / "dest.apk")


def test_cleanup_staged_upload_removes_directory_inside_uploads_dir(tmp_path, monkeypatch):
    staging_root = tmp_path / "uploads"
    staging_root.mkdir()
    monkeypatch.setattr(binary_fetch, "uploads_dir", lambda: staging_root)

    upload_dir = staging_root / "abc123"
    upload_dir.mkdir()
    staged_file = upload_dir / "app.apk"
    staged_file.write_bytes(b"x")

    binary_fetch.cleanup_staged_upload(str(staged_file))

    assert not upload_dir.exists()


def test_cleanup_staged_upload_ignores_path_outside_uploads_dir(tmp_path, monkeypatch):
    # Caminho local digitado à mão pelo usuário (não veio de um upload) —
    # nunca deve ser apagado por engano.
    monkeypatch.setattr(binary_fetch, "uploads_dir", lambda: tmp_path / "uploads")
    outside = tmp_path / "Desktop" / "meu-app.apk"
    outside.parent.mkdir()
    outside.write_bytes(b"x")

    binary_fetch.cleanup_staged_upload(str(outside))

    assert outside.exists()


def test_cleanup_staged_upload_ignores_remote_url():
    binary_fetch.cleanup_staged_upload("https://example.com/app.apk")  # não levanta, não faz nada


def test_validate_apk_accepts_real_apk_shaped_zip(tmp_path):
    path = tmp_path / "ok.apk"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"fake-binary-xml")
        zf.writestr("classes.dex", b"fake-dex")
    binary_fetch.validate_apk(path)  # não levanta


def test_validate_apk_rejects_non_zip_content(tmp_path):
    path = tmp_path / "bad.apk"
    path.write_bytes(b"<html>404 not found</html>")
    with pytest.raises(binary_fetch.BinaryFetchError, match="não parece ser um .apk"):
        binary_fetch.validate_apk(path)


def test_validate_apk_rejects_truncated_zip(tmp_path):
    # Assinatura de zip válida, mas o resto do arquivo não é um zip de
    # verdade — download truncado/corrompido, não só um .apk errado.
    path = tmp_path / "truncated.apk"
    path.write_bytes(b"PK\x03\x04" + b"resto-nao-e-zip-de-verdade")
    with pytest.raises(binary_fetch.BinaryFetchError, match="corrompido ou incompleto"):
        binary_fetch.validate_apk(path)


def test_validate_apk_rejects_aab_disguised_as_apk(tmp_path):
    # .aab também é um .zip válido (passa a assinatura), mas guarda o
    # manifest em base/manifest/ em vez da raiz — não instalável direto.
    path = tmp_path / "app.aab"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("base/manifest/AndroidManifest.xml", b"fake-protobuf-manifest")
    with pytest.raises(binary_fetch.BinaryFetchError, match="\\.aab"):
        binary_fetch.validate_apk(path)


# ─── extract_ios_app / validate_simulator_app / bundle_id_from_app ──────────


def _make_ios_zip(tmp_path, *, platforms=("iPhoneSimulator",), bundle_id="com.example.App", app_name="App", extra_apps=()):
    """Monta um .zip no formato Payload/<Nome>.app/Info.plist, igual a um
    export real de simulador (ou de device, se `platforms` for iPhoneOS) —
    ver investigação ao vivo contra o Sauce Labs My Demo App real."""
    zip_path = tmp_path / "app.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        plist_bytes = plistlib.dumps({"CFBundleSupportedPlatforms": list(platforms), "CFBundleIdentifier": bundle_id})
        zf.writestr(f"Payload/{app_name}.app/Info.plist", plist_bytes)
        zf.writestr(f"Payload/{app_name}.app/{app_name}", b"fake-macho-binary")
        for extra in extra_apps:
            zf.writestr(f"Payload/{extra}.app/Info.plist", plist_bytes)
    return zip_path


def test_extract_ios_app_finds_the_app_bundle(tmp_path):
    zip_path = _make_ios_zip(tmp_path)
    dest = tmp_path / "extracted"
    app_path = binary_fetch.extract_ios_app(zip_path, dest)
    assert app_path.name == "App.app"
    assert (app_path / "Info.plist").exists()


def test_extract_ios_app_raises_when_no_app_found(tmp_path):
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", "nada aqui")
    with pytest.raises(binary_fetch.BinaryFetchError, match="Não encontrei um .app"):
        binary_fetch.extract_ios_app(zip_path, tmp_path / "extracted")


def test_extract_ios_app_raises_when_multiple_apps_found(tmp_path):
    zip_path = _make_ios_zip(tmp_path, extra_apps=("Outro",))
    with pytest.raises(binary_fetch.BinaryFetchError, match="Mais de um .app"):
        binary_fetch.extract_ios_app(zip_path, tmp_path / "extracted")


def test_extract_ios_app_raises_on_invalid_zip(tmp_path):
    bad_zip = tmp_path / "bad.zip"
    bad_zip.write_bytes(b"nao sou um zip")
    with pytest.raises(binary_fetch.BinaryFetchError, match="não parece ser um .zip"):
        binary_fetch.extract_ios_app(bad_zip, tmp_path / "extracted")


def test_validate_simulator_app_accepts_simulator_build(tmp_path):
    zip_path = _make_ios_zip(tmp_path, platforms=("iPhoneSimulator",))
    app_path = binary_fetch.extract_ios_app(zip_path, tmp_path / "extracted")
    binary_fetch.validate_simulator_app(app_path)  # não levanta


def test_validate_simulator_app_rejects_device_build(tmp_path):
    # Regressão do caso real investigado: o .ipa de device do Sauce Labs My
    # Demo App tem CFBundleSupportedPlatforms=["iPhoneOS"], a variante de
    # simulador tem ["iPhoneSimulator"] — mesma estrutura de zip, conteúdo
    # diferente.
    zip_path = _make_ios_zip(tmp_path, platforms=("iPhoneOS",))
    app_path = binary_fetch.extract_ios_app(zip_path, tmp_path / "extracted")
    with pytest.raises(binary_fetch.BinaryFetchError, match="não é um build de SIMULADOR"):
        binary_fetch.validate_simulator_app(app_path)


def test_validate_simulator_app_raises_when_info_plist_missing(tmp_path):
    app_path = tmp_path / "Sem.app"
    app_path.mkdir()
    with pytest.raises(binary_fetch.BinaryFetchError, match="Info.plist não encontrado"):
        binary_fetch.validate_simulator_app(app_path)


def test_bundle_id_from_app_reads_cfbundleidentifier(tmp_path):
    zip_path = _make_ios_zip(tmp_path, bundle_id="com.saucelabs.mydemoapp")
    app_path = binary_fetch.extract_ios_app(zip_path, tmp_path / "extracted")
    assert binary_fetch.bundle_id_from_app(app_path) == "com.saucelabs.mydemoapp"


def test_bundle_id_from_app_raises_when_missing(tmp_path):
    app_path = tmp_path / "Sem.app"
    app_path.mkdir()
    (app_path / "Info.plist").write_bytes(plistlib.dumps({}))
    with pytest.raises(binary_fetch.BinaryFetchError, match="CFBundleIdentifier"):
        binary_fetch.bundle_id_from_app(app_path)
