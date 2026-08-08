"""Argus Agent — tools Appium para o executor do agente mobile (Android).

Espelha o design de `src/tools/web.py`: `MobileSession.snapshot_text()` é a
tool central — em vez de mandar screenshots pro LLM, varre a árvore nativa
via XPath e devolve uma lista textual compacta de elementos visíveis, cada
um com uma ref curta (`e3`); ações então miram por ref. A diferença pro lado
web é como a ref é resolvida: o DOM permite tagear elementos com um atributo
(`data-argus-ref`) que sobrevive entre chamadas de `evaluate()`; uma árvore
de acessibilidade nativa Android não tem esse gancho, então aqui a ref
aponta pra um `WebElement` do Appium cacheado em memória (`self._elements`),
válido só até a PRÓXIMA chamada de snapshot ou até a tela mudar (nesse caso
o elemento fica "stale" e a ação seguinte falha com uma mensagem clara pra
tirar um snapshot novo — mesmo contrato de "ref pode expirar" do lado web)."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from langchain_core.tools import tool
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

# XPath roda contra o page_source cru (dump XML do UiAutomator) — os nomes de
# atributo aqui são os do XML (com hífen), não os aceitos por `get_attribute`
# depois de já ter o elemento (esses usam camelCase, ver `_ATTR_*` abaixo).
_INTERACTIVE_XPATH = "//*[@clickable='true' or @long-clickable='true' or @checkable='true']"
_INFO_XPATH = "//*[@text!='' or @content-desc!='']"
_SNAPSHOT_XPATH = f"({_INTERACTIVE_XPATH}) | ({_INFO_XPATH})"

_CLASS_ROLE_MAP = {
    "android.widget.Button": "button",
    "android.widget.ImageButton": "button",
    "android.widget.EditText": "textbox",
    "android.widget.TextView": "text",
    "android.widget.CheckBox": "checkbox",
    "android.widget.Switch": "switch",
    "android.widget.RadioButton": "radio",
    "android.widget.ImageView": "image",
}


def _role_for(class_name: str, clickable: bool) -> str:
    if class_name in _CLASS_ROLE_MAP:
        return _CLASS_ROLE_MAP[class_name]
    return "button" if clickable else "generic"


class MobileToolError(RuntimeError):
    """Uma tool Appium falhou de um jeito que o LLM deve ver e reagir (ref
    obsoleta, timeout de espera) — nunca deixado propagar cru: vira texto de
    erro devolvido como resultado da tool."""


@dataclass
class MobileSession:
    """Estado vivo de uma run android: driver Appium + package do app sob
    teste (usado por launch/terminate) + onde salvar screenshots. Não é
    serializável (não entra no estado do LangGraph) — vive num registro em
    memória por run_id, ver src/agent/nodes.py (mesmo padrão da WebSession)."""

    driver: WebDriver
    app_package: str
    run_id: str
    artifacts_dir: Path
    scenario_position: int = field(default=0)
    step_position: int = field(default=0)
    _elements: dict[str, Any] = field(default_factory=dict)

    def set_step_context(self, scenario_position: int, step_position: int) -> None:
        self.scenario_position = scenario_position
        self.step_position = step_position

    async def snapshot_text(self) -> str:
        lines_and_elements = await asyncio.to_thread(self._collect_elements)
        activity = await asyncio.to_thread(lambda: self.driver.current_activity)
        lines = [f"Activity: {activity}", ""]
        if not lines_and_elements:
            lines.append("(nenhum elemento visível)")
        lines.extend(lines_and_elements)
        return "\n".join(lines)

    def _collect_elements(self) -> list[str]:
        # Cada chamada revarre e reatribui as refs do zero — refs de uma
        # chamada anterior nunca sobrevivem (mesma lição aprendida do lado
        # web: um cache que persiste sozinho entre chamadas vira uma fonte
        # de bugs sutis quando a tela muda).
        self._elements = {}
        try:
            found = self.driver.find_elements(AppiumBy.XPATH, _SNAPSHOT_XPATH)
        except WebDriverException as e:
            raise MobileToolError(f"Falha ao ler a tela atual: {e}") from e

        rows: list[str] = []
        idx = 0
        for el in found:
            try:
                if not el.is_displayed():
                    continue
                class_name = str(el.get_attribute("className") or "")
                clickable = (el.get_attribute("clickable") or "false") == "true"
                content_desc = str(el.get_attribute("contentDescription") or "")
                text = el.text or ""
                resource_id = str(el.get_attribute("resourceId") or "")
                enabled = (el.get_attribute("enabled") or "true") != "false"
            except StaleElementReferenceException:
                continue
            idx += 1
            ref = f"e{idx}"
            self._elements[ref] = el
            role = _role_for(class_name, clickable)
            name = (content_desc or text or resource_id.rsplit("/", 1)[-1])[:80]
            state = " [desabilitado]" if not enabled else ""
            rows.append(f'[{ref}] {role} "{name}"{state}')
        return rows

    def _require_element(self, ref: str):
        el = self._elements.get(ref)
        if el is None:
            raise MobileToolError(f"Ref {ref} não encontrada — tire um novo snapshot antes de agir.")
        return el

    async def tap(self, ref: str) -> str:
        el = self._require_element(ref)
        try:
            await asyncio.to_thread(el.click)
        except StaleElementReferenceException as e:
            raise MobileToolError(f"Ref {ref} ficou obsoleta (a tela mudou) — tire um novo snapshot.") from e
        return f"Tocou em {ref}.\n\n" + await self.snapshot_text()

    async def type_text(self, ref: str, text: str) -> str:
        el = self._require_element(ref)
        try:
            await asyncio.to_thread(el.send_keys, text)
        except StaleElementReferenceException as e:
            raise MobileToolError(f"Ref {ref} ficou obsoleta (a tela mudou) — tire um novo snapshot.") from e
        return f"Digitou em {ref}."

    async def long_press(self, ref: str) -> str:
        el = self._require_element(ref)
        try:
            await asyncio.to_thread(
                self.driver.execute_script, "mobile: longClickGesture", {"elementId": el.id, "duration": 1000}
            )
        except StaleElementReferenceException as e:
            raise MobileToolError(f"Ref {ref} ficou obsoleta (a tela mudou) — tire um novo snapshot.") from e
        return f"Toque longo em {ref}.\n\n" + await self.snapshot_text()

    async def swipe(self, direction: str) -> str:
        size = await asyncio.to_thread(lambda: self.driver.get_window_size())
        w, h = size["width"], size["height"]
        cx = w // 2
        if direction == "down":
            start_y, end_y = int(h * 0.75), int(h * 0.25)
        elif direction == "up":
            start_y, end_y = int(h * 0.25), int(h * 0.75)
        else:
            raise MobileToolError(f"Direção de swipe inválida: {direction!r} (use 'up' ou 'down').")
        await asyncio.to_thread(self.driver.swipe, cx, start_y, cx, end_y, 400)
        return f"Fez swipe para {direction}."

    async def scroll_to(self, text: str) -> str:
        escaped = text.replace('"', "")
        selector = (
            'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView('
            f'new UiSelector().textContains("{escaped}"))'
        )
        try:
            await asyncio.to_thread(self.driver.find_element, AppiumBy.ANDROID_UIAUTOMATOR, selector)
        except (NoSuchElementException, WebDriverException) as e:
            raise MobileToolError(f'Não consegui rolar até um texto contendo "{text}": {e}') from e
        return f'Rolou até "{text}".\n\n' + await self.snapshot_text()

    async def press_back(self) -> str:
        await asyncio.to_thread(self.driver.back)
        return await self.snapshot_text()

    async def hide_keyboard(self) -> str:
        try:
            await asyncio.to_thread(self.driver.hide_keyboard)
        except WebDriverException:
            pass  # teclado já fechado/nunca aberto — não é um erro pro agente
        return "Teclado escondido (se estava aberto)."

    async def wait_for(self, text: str, timeout_ms: int = 8_000) -> str:
        deadline = time.monotonic() + timeout_ms / 1000
        escaped = text.replace('"', "")
        xpath = f'//*[contains(@text,"{escaped}") or contains(@content-desc,"{escaped}")]'
        while True:
            found = await asyncio.to_thread(self.driver.find_elements, AppiumBy.XPATH, xpath)
            if found:
                return f'Texto "{text}" apareceu.\n\n' + await self.snapshot_text()
            if time.monotonic() > deadline:
                raise MobileToolError(f'Texto "{text}" não apareceu em {timeout_ms}ms.')
            await asyncio.sleep(0.5)

    async def screenshot(self, label: str) -> Path:
        screenshots_dir = self.artifacts_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label) or "evidencia"
        path = screenshots_dir / f"{self.scenario_position}_{self.step_position}_{safe_label}.png"
        await asyncio.to_thread(self.driver.save_screenshot, str(path))
        return path

    async def launch_app(self) -> str:
        await asyncio.to_thread(self.driver.activate_app, self.app_package)
        return "App aberto.\n\n" + await self.snapshot_text()

    async def terminate_app(self) -> str:
        await asyncio.to_thread(self.driver.terminate_app, self.app_package)
        return "App encerrado."


def build_mobile_tools(session: MobileSession) -> list:
    """Fábrica de tools LangChain fechadas sobre uma MobileSession viva —
    mesma razão do `build_web_tools`: uma lista nova por passo garante que a
    sessão sempre é a atual."""

    @tool
    async def mobile_snapshot() -> str:
        """Lê a tela atual do app: lista os elementos visíveis (botões,
        campos, textos) com uma ref curta (ex.: [e3] button "Entrar"). Use
        antes de tocar/digitar para saber as refs atuais — elas mudam a cada
        troca de tela."""
        return await session.snapshot_text()

    @tool
    async def mobile_tap(ref: str) -> str:
        """Toca no elemento identificado pela ref (ex.: "e3"), obtida de um
        mobile_snapshot anterior."""
        try:
            return await session.tap(ref)
        except MobileToolError as e:
            return str(e)

    @tool
    async def mobile_type(ref: str, text: str) -> str:
        """Digita texto num campo identificado pela ref."""
        try:
            return await session.type_text(ref, text)
        except MobileToolError as e:
            return str(e)

    @tool
    async def mobile_long_press(ref: str) -> str:
        """Faz um toque longo no elemento identificado pela ref (útil para
        menus de contexto)."""
        try:
            return await session.long_press(ref)
        except MobileToolError as e:
            return str(e)

    @tool
    async def mobile_swipe(direction: str) -> str:
        """Faz um swipe na tela ("up" ou "down")."""
        try:
            return await session.swipe(direction)
        except MobileToolError as e:
            return str(e)

    @tool
    async def mobile_scroll_to(text: str) -> str:
        """Rola a tela até encontrar um elemento cujo texto contenha o texto
        informado (útil para listas longas sem precisar de vários swipes)."""
        try:
            return await session.scroll_to(text)
        except MobileToolError as e:
            return str(e)

    @tool
    async def mobile_press_back() -> str:
        """Pressiona o botão de voltar (hardware/gesto) do Android."""
        return await session.press_back()

    @tool
    async def mobile_hide_keyboard() -> str:
        """Esconde o teclado virtual, se estiver aberto."""
        return await session.hide_keyboard()

    @tool
    async def mobile_wait_for(text: str, timeout_ms: int = 8000) -> str:
        """Espera até um texto aparecer visível na tela (timeout em ms,
        default 8000). Use antes de declarar que um passo "Then"/"Então"
        falhou — a tela pode estar carregando."""
        try:
            return await session.wait_for(text, timeout_ms)
        except MobileToolError as e:
            return str(e)

    @tool
    async def mobile_screenshot(label: str) -> str:
        """Tira uma screenshot da tela atual como evidência, rotulada com
        `label`."""
        path = await session.screenshot(label)
        return f"Screenshot salva: {path.name}"

    @tool
    async def mobile_launch_app() -> str:
        """Abre (ou traz pra frente) o app sob teste."""
        return await session.launch_app()

    @tool
    async def mobile_terminate_app() -> str:
        """Encerra o app sob teste."""
        return await session.terminate_app()

    return [
        mobile_snapshot, mobile_tap, mobile_type, mobile_long_press, mobile_swipe,
        mobile_scroll_to, mobile_press_back, mobile_hide_keyboard, mobile_wait_for,
        mobile_screenshot, mobile_launch_app, mobile_terminate_app,
    ]
