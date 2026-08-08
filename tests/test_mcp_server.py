"""Testes de src/mcp_server.py — nível 1: as tools como funções Python
puras (o decorator `@mcp_server.tool()` devolve a função original, sem
embrulhar — só registra pra descoberta MCP, então chamar direto testa o
comportamento real). Nível 2: uma chamada de ponta a ponta via HTTP contra
`/mcp` montado em src/main.py, provando que o protocolo (initialize →
tools/list → tools/call) funciona de verdade, não só a lógica Python por
baixo — verificação com um cliente MCP real (Claude Code) é manual, ver
PLANO.md (F5)."""
import asyncio
import itertools

import pytest
from starlette.testclient import TestClient

from src import mcp_server as mcp_module
from src import store
from src.llm_providers import SUPPORTED_PROVIDERS
from src.mcp_server import cancel_run, get_report, get_run_status, list_runs, run_test
from src.user_secrets import set_secret_plain

pytestmark = pytest.mark.anyio

VALID_BDD = "# language: pt\nFuncionalidade: X\n  Cenario: Y\n    Dado algo\n"


@pytest.fixture
def configured_provider():
    provider = SUPPORTED_PROVIDERS[0]
    set_secret_plain(provider.secret_name, "sk-fake-key-not-used")
    store.set_setting("default_llm_provider", provider.id)
    store.set_setting("default_llm_model", provider.example_model)
    return provider


# ─── run_test ─────────────────────────────────────────────────────────────


async def test_run_test_creates_queued_run_without_waiting(configured_provider):
    result = await run_test(platform="web", bdd_script=VALID_BDD, app_url="https://example.com")
    assert result["status"] == "queued"
    assert result["platform"] == "web"


async def test_run_test_returns_error_dict_on_validation_failure(configured_provider):
    result = await run_test(platform="android", bdd_script=VALID_BDD)  # sem binary_url
    assert "error" in result
    assert "binary_url" in result["error"]


async def test_run_test_without_configured_provider_returns_error():
    result = await run_test(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    assert "error" in result
    assert "provider" in result["error"].lower()


async def test_wait_for_terminal_status_returns_once_run_finishes(configured_provider, monkeypatch):
    # Testa o helper de espera isolado (não através de run_test — que cria
    # uma run NOVA a cada chamada, então não daria pra "completar" a mesma
    # run que o fake_sleep está de olho).
    created = await run_test(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    run_id = created["id"]

    async def fake_sleep(_s):
        # Na "próxima verificação" a run já terminou — simula o worker
        # concluindo entre uma checagem e outra.
        store.update_run_status(run_id, "passed", finished_at=True)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    await mcp_module._wait_for_terminal_status(run_id, timeout_seconds=30)
    assert store.get_run(run_id).status == "passed"


async def test_run_test_wait_gives_up_after_timeout_without_erroring(configured_provider, monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    times = itertools.count(step=1000)
    monkeypatch.setattr(mcp_module.time, "monotonic", lambda: next(times))

    result = await run_test(
        platform="web", bdd_script=VALID_BDD, app_url="https://x", wait=True, wait_timeout_seconds=1
    )
    assert result["status"] == "queued"  # nunca chegou a rodar — devolve o estado atual, sem erro


# ─── get_run_status / get_report / list_runs / cancel_run ────────────────


async def test_get_run_status_returns_summary(configured_provider):
    created = await run_test(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    status = await get_run_status(created["id"])
    assert status["id"] == created["id"]


async def test_get_run_status_returns_error_dict_for_unknown_run():
    result = await get_run_status("nao-existe")
    assert "error" in result


async def test_get_report_returns_error_dict_when_not_ready(configured_provider):
    created = await run_test(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    result = await get_report(created["id"])
    assert "error" in result


async def test_get_report_returns_parsed_report(configured_provider, tmp_path):
    import json

    created = await run_test(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    store.set_run_artifacts_dir(created["id"], str(tmp_path))
    (tmp_path / "report.json").write_text(json.dumps({"run": {"id": created["id"]}, "scenarios": []}))
    result = await get_report(created["id"])
    assert result["run"]["id"] == created["id"]


async def test_list_runs_returns_created_run(configured_provider):
    await run_test(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    result = await list_runs(limit=10)
    assert result["total"] >= 1


async def test_cancel_run_marks_cancel_requested(configured_provider):
    created = await run_test(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    result = await cancel_run(created["id"])
    assert result["cancel_requested"] is True
    assert store.is_cancel_requested(created["id"]) is True


async def test_cancel_run_returns_error_dict_for_unknown_run():
    result = await cancel_run("nao-existe")
    assert "error" in result


# ─── ponta a ponta via HTTP contra /mcp (protocolo MCP de verdade) ───────


async def test_mcp_endpoint_lists_the_expected_tools(monkeypatch):
    from src.main import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        init = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
            },
        )
        assert init.status_code == 200
        session_id = init.headers["mcp-session-id"]

        listing = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                "Mcp-Session-Id": session_id,
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert listing.status_code == 200
        body = _parse_sse_json(listing.text)
        tool_names = {t["name"] for t in body["result"]["tools"]}
        assert tool_names == {"run_test", "get_run_status", "get_report", "list_runs", "cancel_run"}


def _parse_sse_json(text: str) -> dict:
    import json

    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: "):])
    raise AssertionError(f"nenhuma linha 'data:' encontrada na resposta SSE:\n{text}")
