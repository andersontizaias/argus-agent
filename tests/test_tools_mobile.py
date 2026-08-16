"""Testes das tools Appium contra um driver/elementos falsos — o executor
mobile de verdade só é verificável com um emulador real (ver PLANO.md); aqui
cobrimos a lógica de parsing/refs/roteamento de erro, que é o que pode
quebrar silenciosamente sem depender de hardware."""
import asyncio
import itertools
from pathlib import Path

import pytest
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

from src.tools import mobile
from src.tools.mobile import MobileSession, MobileToolError, build_mobile_tools

pytestmark = pytest.mark.anyio


class _FakeElement:
    def __init__(self, *, class_name="android.widget.Button", clickable="true", content_desc="",
                 text="", resource_id="", enabled="true", displayed=True, element_id="el-1"):
        self.id = element_id
        self._attrs = {
            "className": class_name, "clickable": clickable, "contentDescription": content_desc,
            "resourceId": resource_id, "enabled": enabled,
        }
        self.text = text
        self._displayed = displayed
        self.clicked = False
        self.sent_keys: str | None = None
        self.stale = False
        self.call_order: list[str] = []

    def is_displayed(self):
        if self.stale:
            raise StaleElementReferenceException("stale")
        return self._displayed

    def get_attribute(self, name):
        if self.stale:
            raise StaleElementReferenceException("stale")
        return self._attrs.get(name)

    def click(self):
        if self.stale:
            raise StaleElementReferenceException("stale")
        self.clicked = True
        self.call_order.append("click")

    def send_keys(self, text):
        if self.stale:
            raise StaleElementReferenceException("stale")
        self.call_order.append("send_keys")
        self.sent_keys = text


class _FakeDriver:
    def __init__(self, elements=None):
        self.elements = elements or []
        self.current_activity = ".MainActivity"
        self.executed: list[tuple[str, dict]] = []
        self.swiped = None
        self.went_back = False
        self.hide_keyboard_called = False
        self.hide_keyboard_error: Exception | None = None
        self.activated: list[str] = []
        self.terminated: list[str] = []
        self.screenshot_paths: list[str] = []
        self.find_element_result = None
        self.find_element_error: Exception | None = None
        self.wait_for_elements: list = []

    def find_elements(self, _by, _value):
        if self.wait_for_elements:
            return self.wait_for_elements.pop(0)
        return self.elements

    def find_element(self, _by, _value):
        if self.find_element_error:
            raise self.find_element_error
        return self.find_element_result

    def execute_script(self, name, args):
        self.executed.append((name, args))

    def get_window_size(self):
        return {"width": 1080, "height": 2400}

    def swipe(self, start_x, start_y, end_x, end_y, duration):
        self.swiped = (start_x, start_y, end_x, end_y, duration)

    def back(self):
        self.went_back = True

    def hide_keyboard(self):
        self.hide_keyboard_called = True
        if self.hide_keyboard_error:
            raise self.hide_keyboard_error

    def activate_app(self, app_id):
        self.activated.append(app_id)

    def terminate_app(self, app_id):
        self.terminated.append(app_id)

    def save_screenshot(self, path):
        self.screenshot_paths.append(path)
        Path(path).write_bytes(b"fake-png")
        return True


def _session(tmp_path, elements=None) -> tuple[MobileSession, _FakeDriver]:
    driver = _FakeDriver(elements=elements)
    session = MobileSession(driver=driver, app_package="com.example.app", run_id="test-run", artifacts_dir=tmp_path)
    return session, driver


class _FakeIOSElement:
    def __init__(self, *, tag_name="XCUIElementTypeButton", label="", name="", value="",
                 enabled="true", displayed=True, element_id="el-1"):
        self.id = element_id
        self.tag_name = tag_name
        self._attrs = {"label": label, "name": name, "value": value, "enabled": enabled}
        self.text = ""
        self._displayed = displayed
        self.clicked = False
        self.sent_keys: str | None = None
        self.stale = False
        self.call_order: list[str] = []

    def is_displayed(self):
        if self.stale:
            raise StaleElementReferenceException("stale")
        return self._displayed

    def get_attribute(self, key):
        if self.stale:
            raise StaleElementReferenceException("stale")
        return self._attrs.get(key)

    def click(self):
        if self.stale:
            raise StaleElementReferenceException("stale")
        self.clicked = True
        self.call_order.append("click")

    def send_keys(self, text):
        if self.stale:
            raise StaleElementReferenceException("stale")
        self.call_order.append("send_keys")
        self.sent_keys = text


def _ios_session(tmp_path, elements=None) -> tuple[MobileSession, _FakeDriver]:
    driver = _FakeDriver(elements=elements)
    session = MobileSession(
        driver=driver, app_package="com.example.App", run_id="test-run", artifacts_dir=tmp_path, platform="ios"
    )
    return session, driver


async def test_snapshot_lists_visible_elements_with_role_and_name(tmp_path):
    button = _FakeElement(class_name="android.widget.Button", content_desc="Entrar")
    session, _ = _session(tmp_path, [button])
    text = await session.snapshot_text()
    assert 'button "Entrar"' in text
    assert "Activity: .MainActivity" in text


async def test_snapshot_falls_back_to_text_then_resource_id_for_name(tmp_path):
    by_text = _FakeElement(text="Bem-vindo")
    by_resource = _FakeElement(resource_id="com.example:id/title", element_id="el-2")
    session, _ = _session(tmp_path, [by_text, by_resource])
    text = await session.snapshot_text()
    assert '"Bem-vindo"' in text
    assert '"title"' in text  # só o último segmento do resource-id


async def test_snapshot_skips_non_displayed_elements(tmp_path):
    hidden = _FakeElement(content_desc="Escondido", displayed=False)
    session, _ = _session(tmp_path, [hidden])
    text = await session.snapshot_text()
    assert "Escondido" not in text
    assert "(nenhum elemento visível)" in text


async def test_snapshot_skips_stale_elements_without_crashing(tmp_path):
    stale = _FakeElement(content_desc="Vai ficar obsoleto")
    stale.stale = True
    ok = _FakeElement(content_desc="Normal", element_id="el-2")
    session, _ = _session(tmp_path, [stale, ok])
    text = await session.snapshot_text()
    assert "Normal" in text
    assert "Vai ficar obsoleto" not in text


async def test_snapshot_marks_disabled_elements(tmp_path):
    disabled = _FakeElement(content_desc="Desabilitado", enabled="false")
    session, _ = _session(tmp_path, [disabled])
    text = await session.snapshot_text()
    assert "[desabilitado]" in text


async def test_snapshot_resets_refs_each_call(tmp_path):
    # Regressão do mesmo bug achado no lado web (src/tools/web.py): refs de
    # uma chamada anterior não podem sobreviver — sempre revarrer do zero.
    el = _FakeElement(content_desc="Item")
    session, driver = _session(tmp_path, [el])
    await session.snapshot_text()
    driver.elements = []  # tela mudou, elemento sumiu
    await session.snapshot_text()
    assert session._elements == {}


async def test_tap_success_returns_new_snapshot(tmp_path):
    el = _FakeElement(content_desc="Entrar")
    session, _ = _session(tmp_path, [el])
    await session.snapshot_text()
    result = await session.tap("e1")
    assert el.clicked is True
    assert "Tocou em e1" in result


async def test_tap_waits_for_the_screen_to_settle_before_snapshotting(tmp_path, monkeypatch):
    # Regressão (achada ao vivo no modo Explorar contra um app real): tirar
    # o snapshot de resultado LOGO após o toque corre o risco de capturar a
    # tela ANTIGA se a transição (rede, animação) ainda não terminou — o
    # agente concluía "toque sem efeito" e declarava CONCLUIDO, enquanto o
    # vídeo da sessão mostrava a navegação completando alguns segundos
    # depois, já fora da janela observada. Só confere que a pausa É
    # chamada com o valor esperado antes do snapshot, sem consumir o tempo
    # de verdade (fake substitui o sleep).
    calls: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr(mobile.asyncio, "sleep", fake_sleep)
    el = _FakeElement(content_desc="Entrar")
    session, _ = _session(tmp_path, [el])
    await session.snapshot_text()

    await session.tap("e1")

    assert calls == [mobile._ACTION_SETTLE_SECONDS]
    await real_sleep(0)  # sanity: o sleep de verdade continua utilizável fora do fake


async def test_tap_unknown_ref_raises_mobile_tool_error(tmp_path):
    session, _ = _session(tmp_path, [])
    with pytest.raises(MobileToolError, match="não encontrada"):
        await session.tap("e999")


async def test_tap_stale_ref_raises_clear_error(tmp_path):
    el = _FakeElement(content_desc="Entrar")
    session, _ = _session(tmp_path, [el])
    await session.snapshot_text()
    el.stale = True
    with pytest.raises(MobileToolError, match="ficou obsoleta"):
        await session.tap("e1")


async def test_type_text_success(tmp_path):
    el = _FakeElement(class_name="android.widget.EditText")
    session, _ = _session(tmp_path, [el])
    await session.snapshot_text()
    await session.type_text("e1", "standard_user")
    assert el.sent_keys == "standard_user"


async def test_type_text_taps_the_field_first_to_ensure_focus(tmp_path):
    # Regressão (achada ao vivo, iOS): `send_keys` sozinho não garante que
    # o campo esteja focado — no XCUITest em especial, digitar sem antes
    # tocar no campo pode não ter efeito nenhum, silenciosamente. `click`
    # precisa acontecer ANTES de `send_keys`, não só em algum momento.
    el = _FakeElement(class_name="android.widget.EditText")
    session, _ = _session(tmp_path, [el])
    await session.snapshot_text()

    await session.type_text("e1", "standard_user")

    assert el.call_order == ["click", "send_keys"]
    assert el.sent_keys == "standard_user"


async def test_long_press_executes_gesture_script(tmp_path):
    el = _FakeElement(content_desc="Item")
    session, driver = _session(tmp_path, [el])
    await session.snapshot_text()
    await session.long_press("e1")
    assert driver.executed[0][0] == "mobile: longClickGesture"
    assert driver.executed[0][1]["elementId"] == el.id


async def test_swipe_down_and_up_directions(tmp_path):
    session, driver = _session(tmp_path, [])
    await session.swipe("down")
    assert driver.swiped is not None
    start_y_down = driver.swiped[1]
    await session.swipe("up")
    start_y_up = driver.swiped[1]
    assert start_y_down != start_y_up


async def test_swipe_invalid_direction_raises(tmp_path):
    session, _ = _session(tmp_path, [])
    with pytest.raises(MobileToolError, match="Direção de swipe inválida"):
        await session.swipe("sideways")


async def test_scroll_to_uses_uiautomator_selector_and_returns_snapshot(tmp_path):
    session, driver = _session(tmp_path, [])
    driver.find_element_result = _FakeElement(content_desc="achou")
    result = await session.scroll_to("Produtos")
    assert 'Rolou até "Produtos"' in result


async def test_scroll_to_raises_when_not_found(tmp_path):
    session, driver = _session(tmp_path, [])
    driver.find_element_error = NoSuchElementException("not found")
    with pytest.raises(MobileToolError, match="Não consegui rolar"):
        await session.scroll_to("Inexistente")


async def test_press_back_calls_driver_back(tmp_path):
    session, driver = _session(tmp_path, [])
    await session.press_back()
    assert driver.went_back is True


async def test_hide_keyboard_swallows_error_when_no_keyboard_open(tmp_path):
    session, driver = _session(tmp_path, [])
    driver.hide_keyboard_error = WebDriverException("no keyboard")
    result = await session.hide_keyboard()  # não levanta
    assert "escondido" in result.lower()


async def test_wait_for_returns_when_text_found_immediately(tmp_path):
    session, driver = _session(tmp_path, [])
    driver.wait_for_elements = [[_FakeElement(text="Bem-vindo")]]
    result = await session.wait_for("Bem-vindo", timeout_ms=1000)
    assert "apareceu" in result


async def test_wait_for_raises_on_timeout(tmp_path, monkeypatch):
    session, driver = _session(tmp_path, [])
    driver.elements = []  # nunca encontra

    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    # Estritamente crescente (não uma lista fixa de valores): código de
    # tracing/instrumentação ao redor da chamada (aqui ou, no teste
    # seguinte, dentro do `.ainvoke()` do LangChain) pode consumir
    # `time.monotonic()` um número imprevisível de vezes ANTES do
    # `wait_for` calcular seu próprio deadline — um valor fixo repetido
    # (`itertools.repeat`) pode ficar preso pra sempre se o deadline for
    # calculado a partir de uma dessas chamadas extras. Incremento sempre
    # maior que qualquer timeout_ms/1000 usado nos testes garante que a
    # PRÓXIMA chamada sempre excede o deadline da anterior.
    times = itertools.count(step=1000)
    monkeypatch.setattr(mobile.time, "monotonic", lambda: next(times))

    with pytest.raises(MobileToolError, match="não apareceu"):
        await session.wait_for("Nunca aparece", timeout_ms=10)


async def test_screenshot_saves_file_named_by_step_context(tmp_path):
    session, _ = _session(tmp_path, [])
    session.set_step_context(scenario_position=1, step_position=2)
    path = await session.screenshot("login ok!")
    assert path.exists()
    assert path.name == "1_2_login_ok_.png"


async def test_launch_app_and_terminate_app(tmp_path):
    session, driver = _session(tmp_path, [])
    await session.launch_app()
    await session.terminate_app()
    assert driver.activated == ["com.example.app"]
    assert driver.terminated == ["com.example.app"]


# ─── build_mobile_tools: as tools LangChain (@tool) que o executor liga ao LLM ──


async def _find_tool(session, name: str):
    tools = build_mobile_tools(session)
    return next(t for t in tools if t.name == name)


async def test_tool_names_cover_the_expected_surface(tmp_path):
    session, _ = _session(tmp_path, [])
    names = {t.name for t in build_mobile_tools(session)}
    assert names == {
        "mobile_snapshot", "mobile_tap", "mobile_type", "mobile_long_press", "mobile_swipe",
        "mobile_scroll_to", "mobile_press_back", "mobile_hide_keyboard", "mobile_wait_for",
        "mobile_screenshot", "mobile_launch_app", "mobile_terminate_app",
    }


async def test_tool_mobile_tap_returns_error_text_instead_of_raising(tmp_path):
    session, _ = _session(tmp_path, [])
    tool = await _find_tool(session, "mobile_tap")
    result = await tool.ainvoke({"ref": "e999"})
    assert "não encontrada" in result


async def test_tool_mobile_wait_for_returns_error_text_on_timeout(tmp_path, monkeypatch):
    session, driver = _session(tmp_path, [])
    driver.elements = []

    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    # Estritamente crescente — ver comentário em test_wait_for_raises_on_timeout:
    # o `.ainvoke()` do LangChain consome `time.monotonic()` antes do `wait_for`
    # calcular seu deadline, então um valor fixo repetido nunca seria excedido.
    times = itertools.count(step=1000)
    monkeypatch.setattr(mobile.time, "monotonic", lambda: next(times))

    tool = await _find_tool(session, "mobile_wait_for")
    result = await tool.ainvoke({"text": "nunca", "timeout_ms": 10})
    assert "não apareceu" in result


async def test_tool_mobile_screenshot(tmp_path):
    session, _ = _session(tmp_path, [])
    tool = await _find_tool(session, "mobile_screenshot")
    result = await tool.ainvoke({"label": "evidencia"})
    assert "Screenshot salva" in result


# ─── iOS (XCUITest) — atributos/gestos são bem diferentes do Android ────────


async def test_ios_snapshot_uses_label_name_value_and_tag_as_role(tmp_path):
    button = _FakeIOSElement(tag_name="XCUIElementTypeButton", label="Entrar")
    session, _ = _ios_session(tmp_path, [button])
    text = await session.snapshot_text()
    assert 'button "Entrar"' in text
    assert "App: com.example.App" in text  # sem current_activity no iOS


async def test_ios_snapshot_falls_back_to_name_then_value_for_text(tmp_path):
    static_text = _FakeIOSElement(tag_name="XCUIElementTypeStaticText", name="Bem-vindo", element_id="el-1")
    field = _FakeIOSElement(tag_name="XCUIElementTypeTextField", value="usuario123", element_id="el-2")
    session, _ = _ios_session(tmp_path, [static_text, field])
    text = await session.snapshot_text()
    assert 'text "Bem-vindo"' in text
    assert 'textbox "usuario123"' in text


async def test_ios_type_text_taps_the_field_first_to_ensure_focus(tmp_path):
    # Regressão achada AO VIVO contra um app iOS de verdade: no XCUITest,
    # `send_keys` num campo que não foi tocado antes pode não digitar NADA
    # — silenciosamente, sem erro, sem teclado aparecendo. O agente
    # "preencheu" o campo sem efeito real até um toque manual (fora do
    # Argus) focar o campo; depois disso um `send_keys` seguinte funcionou.
    field = _FakeIOSElement(tag_name="XCUIElementTypeTextField", element_id="el-1")
    session, _ = _ios_session(tmp_path, [field])
    await session.snapshot_text()

    await session.type_text("e1", "explorer+argus@example.com")

    assert field.call_order == ["click", "send_keys"]
    assert field.sent_keys == "explorer+argus@example.com"


async def test_ios_snapshot_skips_stale_elements_without_crashing(tmp_path):
    stale = _FakeIOSElement(label="Vai sumir")
    stale.stale = True
    ok = _FakeIOSElement(label="Normal", element_id="el-2")
    session, _ = _ios_session(tmp_path, [stale, ok])
    text = await session.snapshot_text()
    assert "Normal" in text
    assert "Vai sumir" not in text


async def test_ios_long_press_uses_touch_and_hold_gesture(tmp_path):
    el = _FakeIOSElement(label="Item")
    session, driver = _ios_session(tmp_path, [el])
    await session.snapshot_text()
    await session.long_press("e1")
    assert driver.executed[0][0] == "mobile: touchAndHold"
    assert driver.executed[0][1]["elementId"] == el.id
    assert driver.executed[0][1]["duration"] == 1.0


async def test_ios_press_back_raises_mobile_tool_error(tmp_path):
    # iOS não tem back de sistema — diferente do Android, isso é um erro
    # claro pro agente tentar outra abordagem (tocar num botão na tela).
    session, driver = _ios_session(tmp_path, [])
    with pytest.raises(MobileToolError, match="não tem um botão de voltar"):
        await session.press_back()
    assert driver.went_back is False


async def test_tool_mobile_press_back_on_ios_returns_error_text_not_raises(tmp_path):
    session, _ = _ios_session(tmp_path, [])
    tool = await _find_tool(session, "mobile_press_back")
    result = await tool.ainvoke({})
    assert "não tem um botão de voltar" in result


async def test_ios_wait_for_matches_name_label_or_value(tmp_path):
    session, driver = _ios_session(tmp_path, [])
    driver.wait_for_elements = [[_FakeIOSElement(label="Bem-vindo")]]
    result = await session.wait_for("Bem-vindo", timeout_ms=1000)
    assert "apareceu" in result


async def test_ios_scroll_to_returns_immediately_when_already_visible(tmp_path):
    session, driver = _ios_session(tmp_path, [])
    driver.wait_for_elements = [[_FakeIOSElement(label="Produtos")]]
    result = await session.scroll_to("Produtos")
    assert 'Rolou até "Produtos"' in result
    assert driver.executed == []  # nem precisou dar scroll


async def test_ios_scroll_to_scrolls_until_found(tmp_path):
    session, driver = _ios_session(tmp_path, [])
    driver.wait_for_elements = [[], [], [_FakeIOSElement(label="Produtos")]]
    result = await session.scroll_to("Produtos")
    assert 'Rolou até "Produtos"' in result
    assert len(driver.executed) == 2  # 2 scrolls antes de achar na 3ª checagem
    assert all(name == "mobile: scroll" for name, _args in driver.executed)


async def test_ios_scroll_to_raises_after_max_attempts(tmp_path):
    session, driver = _ios_session(tmp_path, [])
    driver.wait_for_elements = [[]] * 6
    driver.find_element_error = NoSuchElementException("not found")
    with pytest.raises(MobileToolError, match="Não consegui rolar"):
        await session.scroll_to("Nunca aparece")
