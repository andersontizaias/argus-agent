"""Testes de src/tools/binary_fetch.py — download do binário (mockando
`requests.get`, sem rede de verdade) e validação de assinatura .apk."""
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


def test_validate_apk_accepts_zip_magic(tmp_path):
    path = tmp_path / "ok.apk"
    path.write_bytes(b"PK\x03\x04" + b"resto")
    binary_fetch.validate_apk(path)  # não levanta


def test_validate_apk_rejects_non_zip_content(tmp_path):
    path = tmp_path / "bad.apk"
    path.write_bytes(b"<html>404 not found</html>")
    with pytest.raises(binary_fetch.BinaryFetchError, match="não parece ser um .apk"):
        binary_fetch.validate_apk(path)
