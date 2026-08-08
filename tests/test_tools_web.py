"""Testes das tools Playwright contra uma página HTML real (local, offline —
tests/fixtures/login.html) — prova o snapshot/click/fill/wait_for de verdade,
sem depender de rede nem de LLM."""
from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from src.tools.web import WebSession, WebToolError, build_web_tools

FIXTURE_URL = f"file://{Path(__file__).parent / 'fixtures' / 'login.html'}"

pytestmark = pytest.mark.anyio


@pytest.fixture
async def session(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(FIXTURE_URL)
        yield WebSession(page=page, run_id="test-run", artifacts_dir=tmp_path)
        await browser.close()


async def test_snapshot_lists_visible_interactive_elements(session):
    text = await session.snapshot_text()
    assert '"Username"' in text
    assert '"Password"' in text
    assert "Login" in text
    assert "URL: file://" in text


async def test_snapshot_includes_heading_text(session):
    # Regressão real (achada rodando saucedemo.com de verdade): passos
    # "Then" verificam mensagens de erro/status, quase sempre texto puro
    # (heading, região de alerta) sem nenhum role interativo — sem isso o
    # snapshot nunca "via" a mensagem de erro real do saucedemo (um <h3>).
    text = await session.snapshot_text()
    assert "heading" in text
    assert '"Argus Test Shop"' in text


async def test_snapshot_includes_alert_region_text_after_it_becomes_visible(session):
    snapshot = await session.snapshot_text()
    user_ref = _ref_for(snapshot, "Username")
    pass_ref = _ref_for(snapshot, "Password")
    login_ref = _ref_for(snapshot, "Login")
    await session.fill(user_ref, "wrong_user")
    await session.fill(pass_ref, "wrong_pass")
    await session.click(login_ref)

    text = await session.snapshot_text()
    assert "alert" in text  # role="alert" explícito na fixture
    assert "Usuário ou senha inválidos" in text


async def test_snapshot_retries_once_after_execution_context_destroyed(session):
    # Regressão real (achada rodando contra saucedemo.com de verdade): o
    # evaluate() do snapshot pode pegar a página no meio de uma navegação
    # (redirect JS logo após o load) — "Execution context was destroyed" é
    # um gotcha conhecido do Playwright, não eliminável só escolhendo bem o
    # wait_until do goto. Uma segunda tentativa depois de uma pequena
    # espera resolve na prática.
    real_evaluate = session.page.evaluate
    calls = {"n": 0}

    async def _flaky_evaluate(js):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PlaywrightError("Execution context was destroyed, most likely because of a navigation")
        return await real_evaluate(js)

    session.page.evaluate = _flaky_evaluate  # type: ignore[method-assign]
    text = await session.snapshot_text()
    assert calls["n"] == 2
    assert '"Username"' in text


async def test_snapshot_reraises_unrelated_evaluate_errors(session):
    async def _broken_evaluate(_js):
        raise PlaywrightError("some other unrelated failure")

    session.page.evaluate = _broken_evaluate  # type: ignore[method-assign]
    with pytest.raises(PlaywrightError, match="unrelated failure"):
        await session.snapshot_text()


async def test_navigate_updates_page_and_returns_snapshot(session):
    text = await session.navigate(FIXTURE_URL)
    assert "URL: file://" in text


async def test_fill_and_click_successful_login(session):
    snapshot = await session.snapshot_text()
    user_ref = _ref_for(snapshot, "Username")
    pass_ref = _ref_for(snapshot, "Password")
    login_ref = _ref_for(snapshot, "Login")

    await session.fill(user_ref, "standard_user")
    await session.fill(pass_ref, "secret_sauce")
    result = await session.click(login_ref)

    assert "Products" in result or "Bem-vindo" in await session.page.content()


async def test_fill_and_click_failed_login_shows_error(session):
    snapshot = await session.snapshot_text()
    user_ref = _ref_for(snapshot, "Username")
    pass_ref = _ref_for(snapshot, "Password")
    login_ref = _ref_for(snapshot, "Login")

    await session.fill(user_ref, "wrong_user")
    await session.fill(pass_ref, "wrong_pass")
    await session.click(login_ref)

    result = await session.wait_for("Usuário ou senha inválidos")
    assert "Usuário ou senha inválidos" in result


async def test_wait_for_missing_text_raises_web_tool_error(session):
    with pytest.raises(WebToolError, match="não apareceu"):
        await session.wait_for("texto que nunca vai aparecer", timeout_ms=500)


async def test_click_unknown_ref_raises_web_tool_error(session):
    with pytest.raises(WebToolError, match="não encontrada"):
        await session.click("e999")


async def test_fill_unknown_ref_raises_web_tool_error(session):
    with pytest.raises(WebToolError, match="não encontrada"):
        await session.fill("e999", "x")


async def test_screenshot_saves_file_named_by_step_context(session, tmp_path):
    session.set_step_context(scenario_position=1, step_position=2)
    path = await session.screenshot("login ok!")
    assert path.exists()
    assert path.name == "1_2_login_ok_.png"


async def test_get_url_returns_current_url(session):
    assert (await session.get_url()).startswith("file://")


async def test_scroll_does_not_raise(session):
    await session.scroll("down")
    await session.scroll("up")


async def test_back_navigates_to_previous_page(session):
    await session.navigate(FIXTURE_URL + "#second")
    result = await session.back()
    assert "URL: file://" in result


def _ref_for(snapshot_text: str, name_substring: str) -> str:
    for line in snapshot_text.splitlines():
        if name_substring in line:
            return line.split("]")[0].lstrip("[")
    raise AssertionError(f"Nenhuma linha do snapshot contém {name_substring!r}:\n{snapshot_text}")


# ─── build_web_tools: as tools LangChain (@tool) que o executor liga ao LLM ──


async def _find_tool(session, name: str):
    tools = build_web_tools(session)
    return next(t for t in tools if t.name == name)


async def test_tool_browser_navigate_returns_snapshot(session):
    tool = await _find_tool(session, "browser_navigate")
    result = await tool.ainvoke({"url": FIXTURE_URL})
    assert "URL: file://" in result


async def test_tool_browser_navigate_returns_error_text_on_failure(session):
    tool = await _find_tool(session, "browser_navigate")
    result = await tool.ainvoke({"url": "not-a-valid-url"})
    assert "Erro ao navegar" in result


async def test_tool_browser_snapshot(session):
    tool = await _find_tool(session, "browser_snapshot")
    result = await tool.ainvoke({})
    assert "Login" in result


async def test_tool_browser_click_success_and_unknown_ref(session):
    snapshot = await session.snapshot_text()
    login_ref = _ref_for(snapshot, "Login")
    tool = await _find_tool(session, "browser_click")
    ok_result = await tool.ainvoke({"ref": login_ref})
    assert "Clicou" in ok_result

    await session.navigate(FIXTURE_URL)
    error_result = await tool.ainvoke({"ref": "e999"})
    assert "não encontrada" in error_result


async def test_tool_browser_fill_success_and_unknown_ref(session):
    snapshot = await session.snapshot_text()
    user_ref = _ref_for(snapshot, "Username")
    tool = await _find_tool(session, "browser_fill")
    ok_result = await tool.ainvoke({"ref": user_ref, "text": "standard_user"})
    assert "Preencheu" in ok_result

    error_result = await tool.ainvoke({"ref": "e999", "text": "x"})
    assert "não encontrada" in error_result


async def test_tool_browser_select_unknown_ref_returns_error(session):
    tool = await _find_tool(session, "browser_select")
    result = await tool.ainvoke({"ref": "e999", "value": "x"})
    assert "não encontrada" in result


async def test_tool_browser_press_key(session):
    tool = await _find_tool(session, "browser_press_key")
    result = await tool.ainvoke({"key": "Tab"})
    assert "Pressionou a tecla Tab" in result


async def test_tool_browser_hover_success_and_unknown_ref(session):
    snapshot = await session.snapshot_text()
    login_ref = _ref_for(snapshot, "Login")
    tool = await _find_tool(session, "browser_hover")
    ok_result = await tool.ainvoke({"ref": login_ref})
    assert "Passou o mouse" in ok_result

    error_result = await tool.ainvoke({"ref": "e999"})
    assert "não encontrada" in error_result


async def test_tool_browser_scroll(session):
    tool = await _find_tool(session, "browser_scroll")
    result = await tool.ainvoke({"direction": "down"})
    assert "Rolou" in result


async def test_tool_browser_wait_for_success_and_timeout(session):
    tool = await _find_tool(session, "browser_wait_for")
    ok_result = await tool.ainvoke({"text": "Login", "timeout_ms": 2000})
    assert "apareceu" in ok_result

    timeout_result = await tool.ainvoke({"text": "nunca vai aparecer", "timeout_ms": 300})
    assert "não apareceu" in timeout_result


async def test_tool_browser_screenshot(session):
    tool = await _find_tool(session, "browser_screenshot")
    result = await tool.ainvoke({"label": "evidencia"})
    assert "Screenshot salva" in result


async def test_tool_browser_back(session):
    await session.navigate(FIXTURE_URL + "#x")
    tool = await _find_tool(session, "browser_back")
    result = await tool.ainvoke({})
    assert "URL: file://" in result


async def test_tool_browser_get_url(session):
    tool = await _find_tool(session, "browser_get_url")
    result = await tool.ainvoke({})
    assert result.startswith("file://")
