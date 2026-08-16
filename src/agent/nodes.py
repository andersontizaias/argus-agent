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
import asyncio
import base64
import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.options.ios import XCUITestOptions
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from src import store
from src.agent.executor import (
    StepOutcome,
    run_explore_action,
    run_step,
    synthesize_scenarios,
)
from src.agent.state import RunState
from src.bdd import (
    BddParseError,
    parse_bdd_script,
    resolve_placeholders,
    validate_test_data,
)
from src.events import publish_event
from src.llm_providers import build_chat_model, get_provider
from src.pricing import estimate_cost_usd
from src.report import compile_report as write_report
from src.settings import (
    ANDROID_AVD_NAME,
    ANDROID_EMULATOR_PORT,
    APPIUM_PORT,
    IOS_DEVICE_NAME,
    artifacts_dir,
)
from src.tools import device_android, device_ios
from src.tools.appium_server import AppiumHandle, start_appium, stop_appium
from src.tools.binary_fetch import (
    bundle_id_from_app,
    cleanup_staged_upload,
    extract_ios_app,
    fetch_binary,
    validate_apk,
    validate_simulator_app,
)
from src.tools.device_android import EmulatorHandle
from src.tools.device_ios import SimulatorHandle
from src.tools.mobile import (
    MobileSession,
    build_explore_mobile_tools,
    build_mobile_tools,
)
from src.tools.web import WebSession, build_explore_web_tools, build_web_tools
from src.user_secrets import (
    NO_EXTRA_CREDENTIALS,
    get_bedrock_sigv4_credentials,
    get_secret_plain,
)

logger = logging.getLogger(__name__)

# Sessões vivas (navegador Playwright / driver Appium) por run_id — não são
# serializáveis, então não entram no estado do grafo; um worker que reinicia
# perde a sessão, não o progresso (que está no banco), e `provision_target`
# reprovisiona do zero numa retomada.
_SESSIONS: dict[str, "_RunResources"] = {}

# Emulador Android e simulador iOS são caros de bootar (dezenas de
# segundos) e ficam COMPARTILHADOS entre runs — não são fechados no
# teardown de uma run individual, só quando ficam não-saudáveis (ver
# `_acquire_emulator`/`_acquire_simulator`). O worker processa uma run de
# cada vez (ver src/worker.py), então um único dispositivo compartilhado
# por plataforma basta e evita rebootar a cada run.
_SHARED_EMULATOR: EmulatorHandle | None = None
_EMULATOR_LOCK = asyncio.Lock()
_SHARED_SIMULATOR: SimulatorHandle | None = None
_SIMULATOR_LOCK = asyncio.Lock()


class _RunResources:
    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.web_session: WebSession | None = None
        self.appium: AppiumHandle | None = None
        self.mobile_session: MobileSession | None = None
        # Só usados por mode="explore" (ver _provision_web/_provision_android/
        # _provision_ios + teardown_target): referência ao vídeo da sessão
        # (Playwright só resolve o path DEPOIS do context fechar — por isso
        # guarda a referência aqui, não o path) e se a gravação mobile foi
        # iniciada com sucesso (start_recording_screen pode falhar sem
        # impedir a exploração de rodar — best-effort).
        self.web_video: Any | None = None
        self.mobile_recording_started: bool = False


async def _safe_close_web(resources: "_RunResources") -> None:
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


async def _safe_close_mobile(resources: "_RunResources") -> None:
    """Fecha a sessão do driver Appium e derruba o servidor Appium desta
    run — o EMULADOR/SIMULADOR fica de pé (`_SHARED_EMULATOR`/
    `_SHARED_SIMULATOR`), pra ser reusado pela próxima run mobile sem pagar
    o custo de boot de novo. Comum a Android e iOS — os dois falam Appium."""
    try:
        if resources.mobile_session:
            await asyncio.to_thread(resources.mobile_session.driver.quit)
    except Exception as e:
        logger.warning("Falha ao encerrar a sessão do driver Appium: %s", e)
    try:
        if resources.appium:
            await stop_appium(resources.appium)
    except Exception as e:
        logger.warning("Falha ao derrubar o servidor Appium: %s", e)


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


async def _reset_mobile_app_state(session: MobileSession) -> None:
    """Cada cenário reabre o app do zero — mais simples que uma limpeza
    completa de dados (`mobile: clearApp` no Android; não existe
    equivalente direto no XCUITest), que também derrubaria permissões
    concedidas e efetivamente reinstalaria o app a cada cenário. Não limpa
    dados em disco entre cenários; suficiente pro MVP, documentado como
    limitação conhecida caso vire um problema real com apps que persistem
    estado entre aberturas. `terminate_app`/`activate_app` são chamadas
    genéricas do client Appium — funcionam igual em Android e iOS."""
    await asyncio.to_thread(session.driver.terminate_app, session.app_package)
    await asyncio.to_thread(session.driver.activate_app, session.app_package)


def _fail(state: RunState, run_id: str, message: str) -> RunState:
    store.update_run_status(run_id, "error", error=message)
    publish_event(run_id, "run_error", {"message": message})
    return {**state, "error": message}


async def parse_bdd(state: RunState) -> RunState:
    run_id = state["run_id"]
    run = store.get_run(run_id)
    if not run:
        return _fail(state, run_id, "Run não encontrada.")

    if run.mode == "explore":
        # Sem script de entrada nesse modo — o agente explora sozinho e
        # PRODUZ um (ver explore_app). Nada pra parsear aqui.
        store.update_run_status(run_id, "provisioning")
        publish_event(run_id, "run_provisioning", {"scenarios_total": 0})
        return state

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

    if run.platform == "web":
        return await _provision_web(state, run_id, run)
    if run.platform == "android":
        return await _provision_android(state, run_id, run)
    if run.platform == "ios":
        return await _provision_ios(state, run_id, run)
    return _fail(state, run_id, f"Plataforma '{run.platform}' não suportada.")


async def _provision_web(state: RunState, run_id: str, run) -> RunState:
    resources = _RunResources()
    try:
        resources.playwright = await async_playwright().start()
        resources.browser = await resources.playwright.chromium.launch(headless=True)
        run_dir = artifacts_dir() / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        context_kwargs: dict[str, Any] = {}
        if run.mode == "explore":
            # Vídeo da sessão inteira pra alguém revisar visualmente o que
            # foi capturado (em vez de confiar só no .feature gerado) —
            # gravação nativa do Playwright, só finaliza quando o context
            # fecha (ver teardown_target/_save_web_video_evidence).
            video_dir = run_dir / "video"
            video_dir.mkdir(parents=True, exist_ok=True)
            context_kwargs["record_video_dir"] = str(video_dir)
            context_kwargs["record_video_size"] = {"width": 1280, "height": 720}

        resources.context = await resources.browser.new_context(**context_kwargs)
        page = await resources.context.new_page()
        resources.web_video = page.video
        resources.web_session = WebSession(page=page, run_id=run_id, artifacts_dir=run_dir)
        if run.app_url:
            await page.goto(run.app_url, wait_until="load", timeout=30_000)
    except Exception as e:
        await _safe_close_web(resources)
        return _fail(state, run_id, f"Falha ao provisionar o navegador: {e}")

    _SESSIONS[run_id] = resources
    store.update_run_status(run_id, "running", started_at=True)
    publish_event(run_id, "run_running", {})
    return state


async def _acquire_emulator() -> EmulatorHandle:
    """Reusa o emulador compartilhado se ainda estiver saudável; senão
    (primeira run, ou emulador travou/morreu entre runs) boota um novo —
    mitigação do risco "emuladores frágeis" do PLANO.md (health-check +
    auto-repair em vez de assumir que continua bom)."""
    global _SHARED_EMULATOR
    async with _EMULATOR_LOCK:
        if _SHARED_EMULATOR is not None and await device_android.is_alive(_SHARED_EMULATOR):
            return _SHARED_EMULATOR
        if _SHARED_EMULATOR is not None:
            await device_android.stop_emulator(_SHARED_EMULATOR)
        _SHARED_EMULATOR = await device_android.boot_emulator(ANDROID_AVD_NAME, ANDROID_EMULATOR_PORT)
        return _SHARED_EMULATOR


async def _provision_android(state: RunState, run_id: str, run) -> RunState:
    if not run.binary_url:
        return _fail(state, run_id, "Run android sem binary_url (precisa apontar pro .apk).")

    run_dir = artifacts_dir() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    apk_path = run_dir / "app.apk"

    resources = _RunResources()
    try:
        await fetch_binary(run.binary_url, run.binary_auth_secret, apk_path)
        cleanup_staged_upload(run.binary_url)
        validate_apk(apk_path)

        emulator = await _acquire_emulator()
        resources.appium = await start_appium(APPIUM_PORT)

        options = UiAutomator2Options()
        options.udid = emulator.serial
        options.app = str(apk_path)
        options.automation_name = "UiAutomator2"
        options.new_command_timeout = 300
        options.auto_grant_permissions = True

        driver = await asyncio.to_thread(webdriver.Remote, resources.appium.url, options=options)
        app_package = str(driver.capabilities.get("appPackage") or "")
        resources.mobile_session = MobileSession(
            driver=driver, app_package=app_package, run_id=run_id, artifacts_dir=run_dir, platform="android"
        )
        if run.mode == "explore":
            await _maybe_start_mobile_recording(resources, run_id)
    except Exception as e:
        await _safe_close_mobile(resources)
        return _fail(state, run_id, f"Falha ao provisionar o dispositivo Android: {e}")

    _SESSIONS[run_id] = resources
    store.update_run_status(run_id, "running", started_at=True)
    publish_event(run_id, "run_running", {})
    return state


async def _acquire_simulator() -> SimulatorHandle:
    """Reusa o simulador compartilhado se ainda estiver saudável; senão
    boota um novo — mesma mitigação de risco do `_acquire_emulator`,
    aplicada ao lado iOS."""
    global _SHARED_SIMULATOR
    async with _SIMULATOR_LOCK:
        if _SHARED_SIMULATOR is not None and await device_ios.is_alive(_SHARED_SIMULATOR.udid):
            return _SHARED_SIMULATOR
        if _SHARED_SIMULATOR is not None:
            await device_ios.shutdown_simulator(_SHARED_SIMULATOR)
        _SHARED_SIMULATOR = await device_ios.boot_simulator(IOS_DEVICE_NAME)
        return _SHARED_SIMULATOR


async def _provision_ios(state: RunState, run_id: str, run) -> RunState:
    if not run.binary_url:
        return _fail(state, run_id, "Run ios sem binary_url (precisa apontar pro .zip do build de simulador).")

    run_dir = artifacts_dir() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    zip_path = run_dir / "app.zip"

    resources = _RunResources()
    try:
        await fetch_binary(run.binary_url, run.binary_auth_secret, zip_path)
        cleanup_staged_upload(run.binary_url)
        app_path = extract_ios_app(zip_path, run_dir / "extracted")
        validate_simulator_app(app_path)
        bundle_id = bundle_id_from_app(app_path)

        simulator = await _acquire_simulator()
        resources.appium = await start_appium(APPIUM_PORT)

        options = XCUITestOptions()
        options.udid = simulator.udid
        options.app = str(app_path)
        options.automation_name = "XCUITest"
        options.new_command_timeout = 300

        driver = await asyncio.to_thread(webdriver.Remote, resources.appium.url, options=options)
        resources.mobile_session = MobileSession(
            driver=driver, app_package=bundle_id, run_id=run_id, artifacts_dir=run_dir, platform="ios"
        )
        if run.mode == "explore":
            await _maybe_start_mobile_recording(resources, run_id)
    except Exception as e:
        await _safe_close_mobile(resources)
        return _fail(state, run_id, f"Falha ao provisionar o simulador iOS: {e}")

    _SESSIONS[run_id] = resources
    store.update_run_status(run_id, "running", started_at=True)
    publish_event(run_id, "run_running", {})
    return state


async def run_scenarios(state: RunState) -> RunState:
    run_id = state["run_id"]
    run = store.get_run(run_id)
    resources = _SESSIONS.get(run_id)
    if not run or not resources:
        return state  # provision_target já falhou — nada a fazer aqui

    # Vincula, a partir dos recursos provisionados, a sessão ativa e as
    # funções que dependem da plataforma (montar as tools do passo, resetar
    # o app entre cenários) — o resto desta função fica agnóstico de qual
    # plataforma está rodando.
    session: WebSession | MobileSession
    if resources.web_session is not None:
        web_session = resources.web_session
        session = web_session

        def build_tools() -> list:
            return build_web_tools(web_session)

        async def reset_between_scenarios() -> None:
            await _reset_app_state(resources, run.app_url)
    elif resources.mobile_session is not None:
        mobile_session = resources.mobile_session
        session = mobile_session

        def build_tools() -> list:
            return build_mobile_tools(mobile_session)

        async def reset_between_scenarios() -> None:
            await _reset_mobile_app_state(mobile_session)
    else:
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
    # Bedrock tem um modo avançado (SigV4) além da API key — as 3
    # credenciais extras (ver docstring de src.llm_providers) só existem
    # pra esse provider.
    extra_credentials = get_bedrock_sigv4_credentials() if provider.id == "bedrock" else NO_EXTRA_CREDENTIALS
    chat_model = build_chat_model(provider.id, run.llm_model or provider.example_model, api_key, **extra_credentials)

    test_data = store.get_run_test_data(run_id)

    for scenario in store.list_scenarios(run_id):
        if store.is_cancel_requested(run_id):
            store.update_scenario_status(scenario.id, "skipped")
            continue

        await reset_between_scenarios()
        store.update_scenario_status(scenario.id, "running", started_at=True)
        publish_event(run_id, "scenario_running", {"scenario_id": scenario.id, "name": scenario.name})

        scenario_failed = False
        history: list[str] = []
        for step in store.list_steps(scenario.id):
            if scenario_failed or store.is_cancel_requested(run_id):
                store.update_step_status(step.id, "skipped")
                continue

            session.set_step_context(scenario.position, step.position)
            outcome = await _run_step_with_retry(
                build_tools=build_tools, chat_model=chat_model, keyword=step.keyword,
                step_text=step.text, scenario_name=scenario.name, history=history,
                test_data=test_data,
            )

            if outcome.tokens_in or outcome.tokens_out:
                cost_usd = estimate_cost_usd(
                    run.llm_model or "", tokens_in=outcome.tokens_in, tokens_out=outcome.tokens_out
                )
                store.add_run_usage(
                    run_id, tokens_in=outcome.tokens_in, tokens_out=outcome.tokens_out, cost_usd=cost_usd
                )

            evidence_path = await session.screenshot(f"{step.keyword}_{'ok' if outcome.passed else 'falhou'}")
            store.add_evidence(run_id, step.id, "screenshot", step.keyword, str(evidence_path))

            status = "passed" if outcome.passed else "failed"
            store.update_step_status(step.id, status, error=None if outcome.passed else outcome.message, finished_at=True)
            publish_event(run_id, "step_finished", {"step_id": step.id, "status": status})
            history.append(f"{step.keyword} {step.text} -> {'OK' if outcome.passed else 'FALHOU: ' + outcome.message}")
            if not outcome.passed:
                scenario_failed = True

        final_status = "failed" if scenario_failed else "passed"
        store.update_scenario_status(
            scenario.id, final_status, finished_at=True,
            failure_reason=None if final_status == "passed" else "Um ou mais passos falharam.",
        )
        publish_event(run_id, "scenario_finished", {"scenario_id": scenario.id, "status": final_status})

    return state


async def _run_step_with_retry(
    *, build_tools: Callable[[], list], chat_model, keyword: str, step_text: str, scenario_name: str,
    history: list[str], test_data: dict[str, str],
) -> StepOutcome:
    """1 retry por passo com re-snapshot — resolve flakiness de render (o
    agente tira um snapshot novo a cada tentativa, já que cada chamada é uma
    invocação fresca do executor). Tokens da tentativa que falhou também
    contam pro custo — foram gastos de verdade mesmo sem produzir o
    veredito final."""
    resolved_text = resolve_placeholders(step_text, test_data)
    tokens_in = tokens_out = 0
    for attempt in range(2):
        outcome = await run_step(
            tools=build_tools(), chat_model=chat_model, keyword=keyword,
            step_text=resolved_text, scenario_name=scenario_name, history=history,
        )
        tokens_in += outcome.tokens_in
        tokens_out += outcome.tokens_out
        if outcome.passed or attempt == 1:
            return StepOutcome(outcome.passed, outcome.message, tokens_in, tokens_out)
    return StepOutcome(outcome.passed, outcome.message, tokens_in, tokens_out)  # pragma: no cover — inatingível


async def explore_app(state: RunState) -> RunState:
    """Nó do modo "explore" (paralelo a `run_scenarios`): sem um script BDD
    de entrada, o agente escolhe as próprias ações — uma invocação ReAct
    "fresca" por ação (`run_explore_action`), até declarar CONCLUIDO ou
    esgotar `run.max_actions`. Ao final, uma chamada de síntese SEPARADA
    transforma o trace num `.feature` candidato, validado com
    `parse_bdd_script` antes de salvar (ver docstring de
    `_synthesize_with_validation`)."""
    run_id = state["run_id"]
    run = store.get_run(run_id)
    resources = _SESSIONS.get(run_id)
    if not run or not resources:
        return state  # provision_target já falhou — nada a fazer aqui

    if resources.web_session is not None:
        web_session = resources.web_session
        session: WebSession | MobileSession = web_session
        tools = build_explore_web_tools(web_session, allowed_origin=run.app_url or "")
    elif resources.mobile_session is not None:
        mobile_session = resources.mobile_session
        session = mobile_session
        tools = build_explore_mobile_tools(mobile_session)
    else:
        return state  # provision_target já falhou — nada a fazer aqui

    provider = get_provider(run.llm_provider or "")
    if not provider:
        return _fail(state, run_id, f"Provider LLM desconhecido: {run.llm_provider}")
    api_key = get_secret_plain(provider.secret_name)
    extra_credentials = get_bedrock_sigv4_credentials() if provider.id == "bedrock" else NO_EXTRA_CREDENTIALS
    chat_model = build_chat_model(provider.id, run.llm_model or provider.example_model, api_key, **extra_credentials)

    max_actions = run.max_actions
    history: list[str] = []
    for i in range(max_actions):
        if store.is_cancel_requested(run_id):
            history.append("Exploração cancelada pelo usuário.")
            break

        session.set_step_context(0, i)
        outcome = await run_explore_action(tools=tools, chat_model=chat_model, history=history, max_actions=max_actions)

        if outcome.tokens_in or outcome.tokens_out:
            cost_usd = estimate_cost_usd(
                run.llm_model or "", tokens_in=outcome.tokens_in, tokens_out=outcome.tokens_out
            )
            store.add_run_usage(run_id, tokens_in=outcome.tokens_in, tokens_out=outcome.tokens_out, cost_usd=cost_usd)

        history.append(outcome.description)
        publish_event(run_id, "explore_action", {"index": i, "description": outcome.description, "done": outcome.done})
        if outcome.done:
            break
    else:
        history.append(f"Orçamento de {max_actions} ações esgotado.")

    generated = await _synthesize_with_validation(chat_model=chat_model, trace=history, platform=run.platform, run_id=run_id)
    store.set_run_generated_bdd_script(run_id, generated)
    publish_event(run_id, "explore_finished", {})
    return state


async def _synthesize_with_validation(*, chat_model, trace: list[str], platform: str, run_id: str) -> str:
    """`synthesize_scenarios` nunca levanta, mas o texto que ela devolve pode
    não ser Gherkin válido (o LLM erra sintaxe às vezes) — valida com
    `parse_bdd_script` antes de aceitar; se falhar, tenta MAIS UMA VEZ com o
    erro de sintaxe anexado ao trace (dá pro LLM a chance de se corrigir); se
    falhar de novo, salva mesmo assim como texto anotado — sempre sobra ALGO
    pro usuário revisar, nunca perde o trabalho da exploração."""
    generated = await synthesize_scenarios(chat_model=chat_model, trace=trace, platform=platform)
    try:
        parse_bdd_script(generated)
        return generated
    except BddParseError as e:
        parse_error = str(e)
        logger.warning("Feature gerado pela exploração (run %s) não parseou: %s — tentando de novo.", run_id, parse_error)

    retry_trace = [
        *trace,
        f"(NOTA: a tentativa anterior de escrever o .feature teve um erro de sintaxe Gherkin — corrija: {parse_error})",
    ]
    generated_retry = await synthesize_scenarios(chat_model=chat_model, trace=retry_trace, platform=platform)
    try:
        parse_bdd_script(generated_retry)
        return generated_retry
    except BddParseError as e2:
        logger.warning("Segunda tentativa também não parseou (run %s): %s — salvando como texto bruto.", run_id, e2)
        return (
            f"# ATENÇÃO: este .feature não passou na validação de sintaxe automaticamente "
            f"({e2}) — revise antes de usar.\n\n{generated_retry}"
        )


async def _maybe_start_mobile_recording(resources: "_RunResources", run_id: str) -> None:
    """Best-effort — falhar ao iniciar a gravação não deve impedir a
    exploração de rodar. `resources.mobile_recording_started` fica False se
    isso falhar, e `teardown_target` simplesmente não tenta salvar vídeo
    nenhum nesse caso.

    No iOS, o default do driver XCUITest pra `start_recording_screen` é
    `videoType="mjpeg"` (Motion JPEG) — um codec que NENHUM navegador sabe
    decodificar dentro de um `<video>` HTML5 (achado ao vivo: o player
    ficava preso pra sempre em "carregando", mesmo depois do remux
    "faststart" — o container estava certo, o CODEC que não tocava).
    Força `libx264` (H.264, suportado universalmente) — a própria doc do
    Appium recomenda `pixelFormat="yuv420p"` junto pra compatibilidade
    ampla de player. Android já grava em H.264 nativamente via `adb
    screenrecord` (não tem essa opção — nem precisa)."""
    assert resources.mobile_session is not None
    session = resources.mobile_session
    try:
        if session.platform == "ios":
            await asyncio.to_thread(
                session.driver.start_recording_screen, videoType="libx264", pixelFormat="yuv420p"
            )
        else:
            await asyncio.to_thread(session.driver.start_recording_screen)
        resources.mobile_recording_started = True
    except Exception as e:
        logger.warning("Falha ao iniciar gravação de tela (run %s): %s", run_id, e)


async def _save_web_video_evidence(run_id: str, video: Any) -> None:
    """`video.path()` só resolve DEPOIS do context ter fechado (contrato do
    Playwright) — por isso `teardown_target` chama isso só após
    `_safe_close_web`."""
    try:
        path = await video.path()
        store.add_evidence(run_id, None, "video", "Exploração", str(path))
    except Exception as e:
        logger.warning("Falha ao salvar o vídeo da exploração web (run %s): %s", run_id, e)


def _remux_faststart(path: Path) -> None:
    """`adb screenrecord`/`simctl io recordVideo` gravam o átomo `moov` (o
    índice com a duração/posição dos frames) no FIM do arquivo — não sabem
    a duração total até a gravação parar. Um `<video>` de browser tocando
    via streaming progressivo (nosso endpoint `/api/evidences/{id}`, que já
    suporta Range) precisa do `moov` no INÍCIO pra sequer começar a decodar
    — sem isso, fica preso pra sempre em "carregando" mesmo recebendo dados
    (achado ao vivo: o Chrome fazia as requisições Range certinho, mas o
    player nunca saía do estado `HAVE_NOTHING`). Remuxa só o container
    (`-c copy`, sem reencode — rápido, sem perda) com `ffmpeg -movflags
    +faststart`. Best-effort: se o ffmpeg não estiver instalado ou a
    chamada falhar, mantém o arquivo cru — a evidência ainda fica salva e
    baixável (`Baixar artefatos`), só não toca direto no navegador.

    Rede de segurança independente do CODEC (que é o outro problema real
    que o navegador tinha com o vídeo — ver `_maybe_start_mobile_recording`,
    que força H.264 no iOS): mesmo com um codec suportado, nada garante que
    o `moov` já venha no início por padrão."""
    if not shutil.which("ffmpeg"):
        logger.warning(
            "ffmpeg não encontrado — vídeo da exploração salvo sem remux 'faststart' "
            "(pode não tocar direto no navegador; ainda dá pra baixar e abrir num player local)."
        )
        return
    tmp_path = path.with_suffix(".faststart.mp4")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(tmp_path)],
            capture_output=True,
            timeout=60,
            check=True,
        )
        tmp_path.replace(path)
    except Exception as e:
        logger.warning("Falha ao remuxar o vídeo da exploração pra 'faststart' (mantendo arquivo original): %s", e)
        tmp_path.unlink(missing_ok=True)


async def _save_mobile_video_evidence(run_id: str, session: MobileSession) -> None:
    """Precisa rodar ANTES de `_safe_close_mobile` (que dá `driver.quit()`) —
    ao contrário do lado web, aqui a gravação precisa ser parada enquanto a
    sessão do driver ainda está viva."""
    try:
        b64_video = await asyncio.to_thread(session.driver.stop_recording_screen)
        video_dir = session.artifacts_dir / "video"
        video_dir.mkdir(parents=True, exist_ok=True)
        path = video_dir / "exploracao.mp4"
        path.write_bytes(base64.b64decode(b64_video))
        await asyncio.to_thread(_remux_faststart, path)
        store.add_evidence(run_id, None, "video", "Exploração", str(path))
    except Exception as e:
        logger.warning("Falha ao salvar o vídeo da exploração mobile (run %s): %s", run_id, e)


async def teardown_target(state: RunState) -> RunState:
    run_id = state["run_id"]
    resources = _SESSIONS.pop(run_id, None)
    if not resources:
        return state

    if resources.web_session is not None:
        video = resources.web_video
        await _safe_close_web(resources)
        if video is not None:
            await _save_web_video_evidence(run_id, video)
    elif resources.mobile_session is not None:
        if resources.mobile_recording_started:
            await _save_mobile_video_evidence(run_id, resources.mobile_session)
        await _safe_close_mobile(resources)
    return state


async def compile_report(state: RunState) -> RunState:
    run_id = state["run_id"]
    write_report(run_id)
    publish_event(run_id, "run_finished", {})
    return state
