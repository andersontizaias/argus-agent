"""Argus Agent — nós do StateGraph principal (fases da execução de uma run).

Cada nó representa uma FASE fixa da run (parsing, provisionamento, execução
dos cenários, teardown, relatório). A iteração sobre cenários e passos — de
tamanho dinâmico e variável por run — acontece como controle de fluxo Python
comum *dentro* do nó `run_scenarios`, não como um nó por iteração: o grafo
descreve as fases, não cada passo individual (isso é responsabilidade do
subgrafo ReAct do executor, ver src/agent/executor.py). O estado do
LangGraph (`RunState`) carrega só `run_id`/`error` — cenários/passos/status
vivem no banco (`src.store`), que é a única fonte de verdade tanto para o
relatório quanto pra retomar uma run interrompida."""
import logging

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from src import store
from src.agent.executor import run_step
from src.agent.state import RunState
from src.bdd import (
    BddParseError,
    parse_bdd_script,
    resolve_placeholders,
    validate_test_data,
)
from src.events import publish_event
from src.llm_providers import build_chat_model, get_provider
from src.report import compile_report as write_report
from src.settings import artifacts_dir
from src.tools.web import WebSession
from src.user_secrets import get_secret_plain

logger = logging.getLogger(__name__)

# Sessões vivas (navegador Playwright) por run_id — não são serializáveis,
# então não entram no estado do grafo; um worker que reinicia perde a
# sessão, não o progresso (que está no banco), e `provision_target`
# reprovisiona do zero numa retomada.
_SESSIONS: dict[str, "_RunResources"] = {}


class _RunResources:
    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.web_session: WebSession | None = None


async def _safe_close(resources: "_RunResources") -> None:
    try:
        if resources.context:
            await resources.context.close()
    except Exception as e:  # best-effort — teardown nunca deve levantar
        logger.warning("Falha ao fechar o context: %s", e)
    try:
        if resources.browser:
            await resources.browser.close()
    except Exception as e:
        logger.warning("Falha ao fechar o browser: %s", e)
    try:
        if resources.playwright:
            await resources.playwright.stop()
    except Exception as e:
        logger.warning("Falha ao parar o playwright: %s", e)


async def _reset_app_state(resources: "_RunResources", app_url: str | None) -> None:
    """Cada cenário começa do zero: um context novo (cookies/localStorage/
    sessionStorage limpos) em vez de só navegar de volta — evita que um
    login/estado deixado pelo cenário anterior vaze pro próximo. A
    WebSession troca de página na hora (mesmo objeto, `page` reatribuído)."""
    assert resources.browser is not None and resources.web_session is not None
    old_context = resources.context
    resources.context = await resources.browser.new_context()
    page = await resources.context.new_page()
    resources.web_session.page = page
    if app_url:
        await page.goto(app_url, wait_until="load", timeout=30_000)
    if old_context:
        await old_context.close()


def _fail(state: RunState, run_id: str, message: str) -> RunState:
    store.update_run_status(run_id, "error", error=message)
    publish_event(run_id, "run_error", {"message": message})
    return {**state, "error": message}


async def parse_bdd(state: RunState) -> RunState:
    run_id = state["run_id"]
    run = store.get_run(run_id)
    if not run:
        return _fail(state, run_id, "Run não encontrada.")

    try:
        scenarios = parse_bdd_script(run.bdd_script)
        test_data = store.get_run_test_data(run_id)
        validate_test_data(scenarios, test_data)
    except BddParseError as e:
        return _fail(state, run_id, str(e))

    store.replace_scenarios(run_id, scenarios)
    store.update_run_status(run_id, "provisioning")
    publish_event(run_id, "run_provisioning", {"scenarios_total": len(scenarios)})
    return state


async def provision_target(state: RunState) -> RunState:
    run_id = state["run_id"]
    run = store.get_run(run_id)
    if not run:
        return _fail(state, run_id, "Run não encontrada.")

    if run.platform != "web":
        return _fail(state, run_id, f"Plataforma '{run.platform}' ainda não suportada nesta fase (só 'web').")

    resources = _RunResources()
    try:
        resources.playwright = await async_playwright().start()
        resources.browser = await resources.playwright.chromium.launch(headless=True)
        resources.context = await resources.browser.new_context()
        page = await resources.context.new_page()
        run_dir = artifacts_dir() / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        resources.web_session = WebSession(page=page, run_id=run_id, artifacts_dir=run_dir)
        if run.app_url:
            await page.goto(run.app_url, wait_until="load", timeout=30_000)
    except Exception as e:
        await _safe_close(resources)
        return _fail(state, run_id, f"Falha ao provisionar o navegador: {e}")

    _SESSIONS[run_id] = resources
    store.update_run_status(run_id, "running", started_at=True)
    publish_event(run_id, "run_running", {})
    return state


async def run_scenarios(state: RunState) -> RunState:
    run_id = state["run_id"]
    run = store.get_run(run_id)
    resources = _SESSIONS.get(run_id)
    if not run or not resources or not resources.web_session:
        return state  # provision_target já falhou — nada a fazer aqui

    provider = get_provider(run.llm_provider or "")
    if not provider:
        return _fail(state, run_id, f"Provider LLM desconhecido: {run.llm_provider}")
    # `needs_api_key` é sobre a chave ser OBRIGATÓRIA (ex.: Anthropic sim,
    # Ollama não) — não sobre se ela deve ser enviada quando existe. Ollama
    # aceita uma chave opcional (Bearer token de um reverse proxy na frente
    # do servidor); um `if provider.needs_api_key` aqui mandava sempre ""
    # pro Ollama mesmo com uma chave configurada e válida (mesmo bug do
    # save_config/get_config, corrigido antes — esse era o terceiro lugar).
    api_key = get_secret_plain(provider.secret_name)
    chat_model = build_chat_model(provider.id, run.llm_model or provider.example_model, api_key)

    test_data = store.get_run_test_data(run_id)
    session = resources.web_session

    for scenario in store.list_scenarios(run_id):
        if store.is_cancel_requested(run_id):
            store.update_scenario_status(scenario.id, "skipped")
            continue

        await _reset_app_state(resources, run.app_url)
        store.update_scenario_status(scenario.id, "running", started_at=True)
        publish_event(run_id, "scenario_running", {"scenario_id": scenario.id, "name": scenario.name})

        scenario_failed = False
        history: list[str] = []
        for step in store.list_steps(scenario.id):
            if scenario_failed or store.is_cancel_requested(run_id):
                store.update_step_status(step.id, "skipped")
                continue

            session.set_step_context(scenario.position, step.position)
            passed, message = await _run_step_with_retry(
                session=session, chat_model=chat_model, keyword=step.keyword,
                step_text=step.text, scenario_name=scenario.name, history=history,
                test_data=test_data,
            )

            evidence_path = await session.screenshot(f"{step.keyword}_{'ok' if passed else 'falhou'}")
            store.add_evidence(run_id, step.id, "screenshot", step.keyword, str(evidence_path))

            status = "passed" if passed else "failed"
            store.update_step_status(step.id, status, error=None if passed else message, finished_at=True)
            publish_event(run_id, "step_finished", {"step_id": step.id, "status": status})
            history.append(f"{step.keyword} {step.text} -> {'OK' if passed else 'FALHOU: ' + message}")
            if not passed:
                scenario_failed = True

        final_status = "failed" if scenario_failed else "passed"
        store.update_scenario_status(
            scenario.id, final_status, finished_at=True,
            failure_reason=None if final_status == "passed" else "Um ou mais passos falharam.",
        )
        publish_event(run_id, "scenario_finished", {"scenario_id": scenario.id, "status": final_status})

    return state


async def _run_step_with_retry(
    *, session: WebSession, chat_model, keyword: str, step_text: str, scenario_name: str,
    history: list[str], test_data: dict[str, str],
) -> tuple[bool, str]:
    """1 retry por passo com re-snapshot — resolve flakiness de render (o
    agente tira um snapshot novo a cada tentativa, já que cada chamada é uma
    invocação fresca do executor)."""
    resolved_text = resolve_placeholders(step_text, test_data)
    for attempt in range(2):
        passed, message = await run_step(
            session=session, chat_model=chat_model, keyword=keyword,
            step_text=resolved_text, scenario_name=scenario_name, history=history,
        )
        if passed or attempt == 1:
            return passed, message
    return passed, message  # pragma: no cover — inatingível, loop sempre retorna acima


async def teardown_target(state: RunState) -> RunState:
    run_id = state["run_id"]
    resources = _SESSIONS.pop(run_id, None)
    if resources:
        await _safe_close(resources)
    return state


async def compile_report(state: RunState) -> RunState:
    run_id = state["run_id"]
    write_report(run_id)
    publish_event(run_id, "run_finished", {})
    return state
