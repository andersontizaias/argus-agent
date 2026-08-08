"""Teste de integração ponta a ponta do grafo principal — o equivalente
automatizado/CI-safe da verificação da F1 ("run contra site demo com 1
cenário que passa e 1 que falha de propósito produz report.json correto e
screenshots por passo"): usa a página local de fixture (real Playwright, sem
rede) no lugar do saucedemo.com, e substitui a chamada ao LLM por um
executor determinístico que interpreta os passos e interage com a página de
verdade — o objetivo aqui é provar a orquestração (parse → provisiona →
executa cenários → screenshots → relatório → status final), não o
tool-calling do LLM (isso já é coberto por tests/test_executor.py)."""
import json
import re
from pathlib import Path

import pytest

from src import store
from src.agent.graph import run_graph
from src.llm_providers import SUPPORTED_PROVIDERS
from src.user_secrets import set_secret_plain

FIXTURE_URL = f"file://{Path(__file__).parent / 'fixtures' / 'login.html'}"

BDD_SCRIPT = """\
# language: pt
Funcionalidade: Login
  Cenário: Login válido
    Dado que estou na página de login
    Quando preencho usuário "standard_user"
    E preencho senha "secret_sauce"
    E clico em entrar
    Então vejo a lista de produtos

  Cenário: Login inválido de propósito
    Dado que estou na página de login
    Quando preencho usuário "usuario_errado"
    E clico em entrar
    Então vejo a lista de produtos
"""

pytestmark = pytest.mark.anyio


async def _fake_run_step(*, session, chat_model, keyword, step_text, scenario_name, history):
    """Substitui o LLM: interpreta o passo com regex simples e age na página
    de verdade — prova a orquestração sem custo/flakiness de LLM real."""
    if "página de login" in step_text:
        return True, "ok"

    match = re.search(r'preencho usuário "([^"]+)"', step_text)
    if match:
        snapshot = await session.snapshot_text()
        ref = next(line.split("]")[0][1:] for line in snapshot.splitlines() if "Username" in line)
        await session.fill(ref, match.group(1))
        return True, "ok"

    match = re.search(r'preencho senha "([^"]+)"', step_text)
    if match:
        snapshot = await session.snapshot_text()
        ref = next(line.split("]")[0][1:] for line in snapshot.splitlines() if "Password" in line)
        await session.fill(ref, match.group(1))
        return True, "ok"

    if "clico em entrar" in step_text:
        snapshot = await session.snapshot_text()
        ref = next(line.split("]")[0][1:] for line in snapshot.splitlines() if "Login" in line)
        await session.click(ref)
        return True, "ok"

    if "vejo a lista de produtos" in step_text:
        # page.content() devolve o HTML bruto (inclui elementos com
        # display:none) — precisa checar o texto renderizado de verdade.
        visible_text = await session.page.inner_text("body")
        if "Products" in visible_text:
            return True, "Lista de produtos visível."
        return False, "Lista de produtos não apareceu — login não foi bem-sucedido."

    raise AssertionError(f"passo inesperado no fake executor: {step_text}")


@pytest.fixture(autouse=True)
def _configure_provider():
    # provider/modelo não importam pra esse teste (run_step é substituído),
    # mas run_scenarios monta o chat_model antes de chamá-lo — precisa de
    # um provider "configurado" pra passar por ali sem erro.
    provider = SUPPORTED_PROVIDERS[0]
    set_secret_plain(provider.secret_name, "sk-fake-key-not-used")
    return provider


async def test_full_run_produces_correct_report_and_screenshots(monkeypatch, _configure_provider):
    monkeypatch.setattr("src.agent.nodes.run_step", _fake_run_step)

    run = store.create_run(
        platform="web",
        app_url=FIXTURE_URL,
        bdd_script=BDD_SCRIPT,
        llm_provider=_configure_provider.id,
        llm_model=_configure_provider.example_model,
    )

    await run_graph(run.id)

    final_run = store.get_run(run.id)
    assert final_run.status == "failed"  # um cenário falhou de propósito
    assert final_run.scenarios_total == 2
    assert final_run.scenarios_passed == 1
    assert final_run.scenarios_failed == 1
    assert final_run.started_at is not None
    assert final_run.finished_at is not None

    scenarios = store.list_scenarios(run.id)
    valid, invalid = scenarios[0], scenarios[1]
    assert valid.status == "passed"
    assert invalid.status == "failed"
    assert invalid.failure_reason

    steps = store.list_steps(invalid.id)
    assert steps[-1].status == "failed"
    assert "não apareceu" in steps[-1].error

    assert final_run.artifacts_dir is not None
    report_path = Path(final_run.artifacts_dir) / "report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text())
    assert report["run"]["status"] == "failed"
    assert report["run"]["scenarios_passed"] == 1
    assert len(report["scenarios"]) == 2
    assert report["scenarios"][0]["status"] == "passed"
    assert report["scenarios"][1]["status"] == "failed"

    # Screenshot por passo — pelo menos um step de cada cenário tem evidência.
    for scenario in report["scenarios"]:
        for step in scenario["steps"]:
            assert len(step["evidences"]) == 1
            screenshot_path = Path(final_run.artifacts_dir) / step["evidences"][0]["path"]
            assert screenshot_path.exists()

    html_path = Path(final_run.artifacts_dir) / "report.html"
    assert html_path.exists()
    assert "Login válido" in html_path.read_text()


async def test_run_with_missing_placeholder_data_marks_run_as_error():
    run = store.create_run(
        platform="web",
        app_url=FIXTURE_URL,
        bdd_script="# language: pt\nFuncionalidade: X\n  Cenário: Y\n    Quando preencho <campo_inexistente>\n",
    )

    await run_graph(run.id)

    final_run = store.get_run(run.id)
    assert final_run.status == "error"
    assert "campo_inexistente" in final_run.error


async def test_run_with_unsupported_platform_marks_run_as_error():
    run = store.create_run(
        platform="android",
        binary_url="https://example.com/app.apk",
        bdd_script="# language: pt\nFuncionalidade: X\n  Cenário: Y\n    Dado algo\n",
    )

    await run_graph(run.id)

    final_run = store.get_run(run.id)
    assert final_run.status == "error"
    assert "android" in final_run.error


async def test_cancel_requested_before_scenario_marks_it_skipped(monkeypatch, _configure_provider):
    async def _instant_cancel_run_step(**kwargs):
        raise AssertionError("não deveria executar nenhum passo — run já foi cancelada")

    monkeypatch.setattr("src.agent.nodes.run_step", _instant_cancel_run_step)

    run = store.create_run(
        platform="web", app_url=FIXTURE_URL, bdd_script=BDD_SCRIPT,
        llm_provider=_configure_provider.id, llm_model=_configure_provider.example_model,
    )
    store.request_cancel(run.id)

    await run_graph(run.id)

    scenarios = store.list_scenarios(run.id)
    assert all(s.status == "skipped" for s in scenarios)
    assert store.get_run(run.id).status == "canceled"
