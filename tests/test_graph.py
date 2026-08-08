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
from typing import ClassVar

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


def _tool(tools, name: str):
    return next(t for t in tools if t.name == name)


async def _fake_run_step(*, tools, chat_model, keyword, step_text, scenario_name, history):
    """Substitui o LLM: interpreta o passo com regex simples e age na página
    de verdade através das MESMAS tools que o agente real usaria (não mexe
    na sessão por baixo do pano) — prova a orquestração sem custo/flakiness
    de LLM real."""
    if "página de login" in step_text:
        return True, "ok"

    match = re.search(r'preencho usuário "([^"]+)"', step_text)
    if match:
        snapshot = await _tool(tools, "browser_snapshot").ainvoke({})
        ref = next(line.split("]")[0][1:] for line in snapshot.splitlines() if "Username" in line)
        await _tool(tools, "browser_fill").ainvoke({"ref": ref, "text": match.group(1)})
        return True, "ok"

    match = re.search(r'preencho senha "([^"]+)"', step_text)
    if match:
        snapshot = await _tool(tools, "browser_snapshot").ainvoke({})
        ref = next(line.split("]")[0][1:] for line in snapshot.splitlines() if "Password" in line)
        await _tool(tools, "browser_fill").ainvoke({"ref": ref, "text": match.group(1)})
        return True, "ok"

    if "clico em entrar" in step_text:
        snapshot = await _tool(tools, "browser_snapshot").ainvoke({})
        ref = next(line.split("]")[0][1:] for line in snapshot.splitlines() if "Login" in line)
        await _tool(tools, "browser_click").ainvoke({"ref": ref})
        return True, "ok"

    if "vejo a lista de produtos" in step_text:
        # O snapshot já inclui headings (ver src/tools/web.py) — "Products"
        # aparece como texto mesmo sem ser um elemento interativo.
        snapshot = await _tool(tools, "browser_snapshot").ainvoke({})
        if "Products" in snapshot:
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
    # "android" ganhou suporte nesta fase (F3) — "ios" é a próxima
    # plataforma ainda não implementada (F4), então é ela que exercita o
    # branch de "plataforma não suportada" agora.
    run = store.create_run(
        platform="ios",
        binary_url="https://example.com/app.zip",
        bdd_script="# language: pt\nFuncionalidade: X\n  Cenário: Y\n    Dado algo\n",
    )

    await run_graph(run.id)

    final_run = store.get_run(run.id)
    assert final_run.status == "error"
    assert "ios" in final_run.error


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


async def test_run_scenarios_sends_configured_ollama_api_key(monkeypatch):
    # Regressão real (achada rodando contra um Ollama remoto de verdade
    # atrás de proxy com auth): `needs_api_key=False` do Ollama é sobre a
    # chave ser OPCIONAL, não sobre nunca deve ser enviada — `run_scenarios`
    # tinha um `if provider.needs_api_key` que mandava sempre "" pro
    # build_chat_model, mesmo com uma chave configurada e válida. O
    # "Testar provider" (routers/config.py) já usava o caminho certo, então
    # esse bug só aparecia numa run de verdade, nunca no botão de teste.
    set_secret_plain("ollama_api_key", "meu-bearer-token-secreto")
    store.set_setting("ollama_base_url", "http://localhost:11434")

    captured_api_keys = []

    def _fake_build_chat_model(_provider_id, _model, api_key, **_kwargs):
        captured_api_keys.append(api_key)
        return object()

    async def _fake_pass_step(**_kwargs):
        return True, "ok"

    monkeypatch.setattr("src.agent.nodes.build_chat_model", _fake_build_chat_model)
    monkeypatch.setattr("src.agent.nodes.run_step", _fake_pass_step)

    run = store.create_run(
        platform="web", app_url=FIXTURE_URL,
        bdd_script="# language: pt\nFuncionalidade: X\n  Cenario: Y\n    Dado algo\n",
        llm_provider="ollama", llm_model="qwen3-coder:30b",
    )

    await run_graph(run.id)

    assert captured_api_keys == ["meu-bearer-token-secreto"]


async def test_android_run_provisions_and_tears_down_with_mocked_device_layer(monkeypatch, _configure_provider):
    """Prova a orquestração de provisionamento/teardown android (baixa o
    apk → boota/reusa o emulador → sobe o Appium → abre a sessão do driver
    → roda o cenário → teardown fecha driver+Appium sem derrubar o
    emulador compartilhado) com a camada de dispositivo mockada — o
    caminho real (emulador/Appium/driver de verdade) só é verificável
    localmente com hardware, ver PLANO.md (F3.4)."""
    from src.agent import nodes as nodes_module
    from src.tools.appium_server import AppiumHandle
    from src.tools.device_android import EmulatorHandle

    async def _fake_fetch_binary(_url, _secret, dest_path, **_kw):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"PK\x03\x04fake-apk-content")
        return dest_path

    fake_emulator = EmulatorHandle(avd_name="Pixel_9a", port=5554, serial="emulator-5554", process=None)
    fake_appium = AppiumHandle(port=4723, process=None)

    class _FakeDriver:
        capabilities: ClassVar = {"appPackage": "com.example.app"}
        quit_called = False

        def quit(self):
            _FakeDriver.quit_called = True

        def terminate_app(self, _app_id):
            pass

        def activate_app(self, _app_id):
            pass

        def save_screenshot(self, path):
            Path(path).write_bytes(b"fake-png")
            return True

    calls = {"boot_emulator": 0, "stop_appium": 0, "stop_emulator": 0}

    async def _fake_boot_emulator(*_a, **_kw):
        calls["boot_emulator"] += 1
        return fake_emulator

    async def _fake_is_alive(_handle):
        return True

    async def _fake_stop_emulator(_handle):
        calls["stop_emulator"] += 1

    async def _fake_start_appium(*_a, **_kw):
        return fake_appium

    async def _fake_stop_appium(_handle):
        calls["stop_appium"] += 1

    async def _fake_pass_step(**_kwargs):
        return True, "ok"

    monkeypatch.setattr(nodes_module, "fetch_binary", _fake_fetch_binary)
    monkeypatch.setattr(nodes_module, "validate_apk", lambda _path: None)
    monkeypatch.setattr(nodes_module.device_android, "boot_emulator", _fake_boot_emulator)
    monkeypatch.setattr(nodes_module.device_android, "is_alive", _fake_is_alive)
    monkeypatch.setattr(nodes_module.device_android, "stop_emulator", _fake_stop_emulator)
    monkeypatch.setattr(nodes_module, "start_appium", _fake_start_appium)
    monkeypatch.setattr(nodes_module, "stop_appium", _fake_stop_appium)
    monkeypatch.setattr(nodes_module.webdriver, "Remote", lambda *_a, **_kw: _FakeDriver())
    monkeypatch.setattr(nodes_module, "run_step", _fake_pass_step)
    # o emulador compartilhado é estado de módulo — garante que este teste
    # não herda (nem vaza) um handle de outro teste rodando na mesma sessão.
    monkeypatch.setattr(nodes_module, "_SHARED_EMULATOR", None)

    run = store.create_run(
        platform="android", binary_url="https://example.com/app.apk",
        bdd_script="# language: pt\nFuncionalidade: X\n  Cenario: Y\n    Dado algo\n",
        llm_provider=_configure_provider.id, llm_model=_configure_provider.example_model,
    )

    await run_graph(run.id)

    final_run = store.get_run(run.id)
    assert final_run.status == "passed"
    assert calls["boot_emulator"] == 1
    assert calls["stop_appium"] == 1
    assert calls["stop_emulator"] == 0  # emulador fica de pé pra reuso, teardown não derruba
    assert _FakeDriver.quit_called is True


async def test_android_run_without_binary_url_marks_run_as_error():
    run = store.create_run(
        platform="android",
        bdd_script="# language: pt\nFuncionalidade: X\n  Cenário: Y\n    Dado algo\n",
    )

    await run_graph(run.id)

    final_run = store.get_run(run.id)
    assert final_run.status == "error"
    assert "binary_url" in final_run.error


async def test_android_provisioning_failure_marks_run_as_error_not_failed(monkeypatch):
    # Falha de PROVISIONAMENTO (download do apk, boot do emulador, etc.) é
    # `error`, não `failed` — nenhum cenário chegou a rodar, então não faz
    # sentido reportar como "cenário reprovado" (ver compile_report).
    from src.agent import nodes as nodes_module

    async def _fake_fetch_binary_fails(*_a, **_kw):
        raise RuntimeError("download falhou")

    monkeypatch.setattr(nodes_module, "fetch_binary", _fake_fetch_binary_fails)

    run = store.create_run(
        platform="android", binary_url="https://example.com/app.apk",
        bdd_script="# language: pt\nFuncionalidade: X\n  Cenário: Y\n    Dado algo\n",
    )

    await run_graph(run.id)

    final_run = store.get_run(run.id)
    assert final_run.status == "error"
    assert "Falha ao provisionar o dispositivo Android" in final_run.error
