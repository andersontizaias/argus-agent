"""Argus Agent — tools Appium para o executor do agente mobile (Android via
UiAutomator2, iOS via XCUITest).

Espelha o design de `src/tools/web.py`: `MobileSession.snapshot_text()` é a
tool central — em vez de mandar screenshots pro LLM, varre a árvore nativa
via XPath e devolve uma lista textual compacta de elementos visíveis, cada
um com uma ref curta (`e3`); ações então miram por ref. A diferença pro lado
web é como a ref é resolvida: o DOM permite tagear elementos com um atributo
(`data-argus-ref`) que sobrevive entre chamadas de `evaluate()`; uma árvore
de acessibilidade nativa não tem esse gancho, então aqui a ref aponta pra um
`WebElement` do Appium cacheado em memória (`self._elements`), válido só até
a PRÓXIMA chamada de snapshot ou até a tela mudar (nesse caso o elemento
fica "stale" e a ação seguinte falha com uma mensagem clara pra tirar um
snapshot novo — mesmo contrato de "ref pode expirar" do lado web).

Android (UiAutomator2) e iOS (XCUITest) falam protocolos de acessibilidade
BEM diferentes — nomes de atributo, tipos de elemento, gestos nomeados
("mobile: X") não têm equivalência 1:1. Em vez de duas classes paralelas
(muita duplicação pras ~80% das tools que são idênticas — tap/type/wait_for/
screenshot/launch/terminate), `MobileSession` recebe um `platform` e os
poucos pontos que realmente divergem (`_collect_elements`, `long_press`,
`scroll_to`, `press_back`, `wait_for`) branch internamente. `swipe` é a
única ação de gesto que É genérica (usa W3C Actions puro, sem comando
nomeado por plataforma)."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from langchain_core.tools import tool
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

from src.tools.explore_guardrails import DANGEROUS_ACTION_REFUSAL, is_dangerous_action

Platform = Literal["android", "ios"]

# Pausa após um toque antes de tirar o snapshot de "resultado" — dá tempo
# pra uma transição assíncrona (rede, animação) terminar antes de julgar se
# a tela mudou. Ver comentário em `MobileSession.tap`.
_ACTION_SETTLE_SECONDS = 1.5

# ─── Android (UiAutomator2): XPath roda contra o page_source cru (dump XML
# do UiAutomator) — os nomes de atributo aqui são os do XML (com hífen), não
# os aceitos por `get_attribute` depois de já ter o elemento (esses usam
# camelCase). ────────────────────────────────────────────────────────────
_ANDROID_INTERACTIVE_XPATH = "//*[@clickable='true' or @long-clickable='true' or @checkable='true']"
_ANDROID_INFO_XPATH = "//*[@text!='' or @content-desc!='']"
_ANDROID_SNAPSHOT_XPATH = f"({_ANDROID_INTERACTIVE_XPATH}) | ({_ANDROID_INFO_XPATH})"

_ANDROID_CLASS_ROLE_MAP = {
    "android.widget.Button": "button",
    "android.widget.ImageButton": "button",
    "android.widget.EditText": "textbox",
    "android.widget.TextView": "text",
    "android.widget.CheckBox": "checkbox",
    "android.widget.Switch": "switch",
    "android.widget.RadioButton": "radio",
    "android.widget.ImageView": "image",
}


def _android_role_for(class_name: str, clickable: bool) -> str:
    if class_name in _ANDROID_CLASS_ROLE_MAP:
        return _ANDROID_CLASS_ROLE_MAP[class_name]
    return "button" if clickable else "generic"


# ─── iOS (XCUITest): não existe um atributo "clickable" — interatividade é
# implícita no TIPO do elemento (a tag XML É o tipo, ex.: XCUIElementTypeButton).
# ────────────────────────────────────────────────────────────────────────
_IOS_INTERACTIVE_TYPES = (
    "XCUIElementTypeButton", "XCUIElementTypeTextField", "XCUIElementTypeSecureTextField",
    "XCUIElementTypeSwitch", "XCUIElementTypeLink", "XCUIElementTypeCell",
    "XCUIElementTypeSegmentedControl", "XCUIElementTypeSlider", "XCUIElementTypeSearchField",
    "XCUIElementTypePickerWheel", "XCUIElementTypeKey",
)
_IOS_SNAPSHOT_XPATH = " | ".join(f"//{t}" for t in _IOS_INTERACTIVE_TYPES) + \
    ' | //XCUIElementTypeStaticText[@name!="" or @label!=""]'

_IOS_TYPE_ROLE_MAP = {
    "XCUIElementTypeButton": "button",
    "XCUIElementTypeTextField": "textbox",
    "XCUIElementTypeSecureTextField": "textbox",
    "XCUIElementTypeSearchField": "textbox",
    "XCUIElementTypeSwitch": "switch",
    "XCUIElementTypeLink": "link",
    "XCUIElementTypeCell": "cell",
    "XCUIElementTypeSegmentedControl": "segmented",
    "XCUIElementTypeSlider": "slider",
    "XCUIElementTypePickerWheel": "picker",
    "XCUIElementTypeKey": "key",
    "XCUIElementTypeStaticText": "text",
}


def _ios_role_for(element_type: str) -> str:
    return _IOS_TYPE_ROLE_MAP.get(element_type, "generic")


class MobileToolError(RuntimeError):
    """Uma tool Appium falhou de um jeito que o LLM deve ver e reagir (ref
    obsoleta, timeout de espera) — nunca deixado propagar cru: vira texto de
    erro devolvido como resultado da tool."""


@dataclass
class MobileSession:
    """Estado vivo de uma run mobile: driver Appium + identificador do app
    sob teste (package Android ou bundle id iOS — usado por launch/
    terminate) + onde salvar screenshots. Não é serializável (não entra no
    estado do LangGraph) — vive num registro em memória por run_id, ver
    src/agent/nodes.py (mesmo padrão da WebSession)."""

    driver: WebDriver
    app_package: str
    run_id: str
    artifacts_dir: Path
    platform: Platform = "android"
    scenario_position: int = field(default=0)
    step_position: int = field(default=0)
    _elements: dict[str, Any] = field(default_factory=dict)
    # Ref -> "role \"name\"" do último snapshot — mesma razão do
    # `WebSession.last_elements`, ver lá: usado só pelo modo "explore" pra
    # checar o alvo antes de agir, sem depender do LLM autorrelatar.
    last_element_labels: dict[str, str] = field(default_factory=dict)

    def element_label(self, ref: str) -> str:
        return self.last_element_labels.get(ref, ref)

    def set_step_context(self, scenario_position: int, step_position: int) -> None:
        self.scenario_position = scenario_position
        self.step_position = step_position

    async def snapshot_text(self) -> str:
        lines_and_elements = await asyncio.to_thread(self._collect_elements)
        header = await asyncio.to_thread(self._header_line)
        lines = [header, ""]
        if not lines_and_elements:
            lines.append("(nenhum elemento visível)")
        lines.extend(lines_and_elements)
        return "\n".join(lines)

    def _header_line(self) -> str:
        if self.platform == "android":
            return f"Activity: {self.driver.current_activity}"
        return f"App: {self.app_package}"

    def _collect_elements(self) -> list[str]:
        # Cada chamada revarre e reatribui as refs do zero — refs de uma
        # chamada anterior nunca sobrevivem (mesma lição aprendida do lado
        # web: um cache que persiste sozinho entre chamadas vira uma fonte
        # de bugs sutis quando a tela muda).
        self._elements = {}
        self.last_element_labels = {}
        xpath = _ANDROID_SNAPSHOT_XPATH if self.platform == "android" else _IOS_SNAPSHOT_XPATH
        try:
            found = self.driver.find_elements(AppiumBy.XPATH, xpath)
        except WebDriverException as e:
            raise MobileToolError(f"Falha ao ler a tela atual: {e}") from e

        rows: list[str] = []
        idx = 0
        for el in found:
            try:
                if not el.is_displayed():
                    continue
                role, name, enabled = self._describe_element(el)
            except StaleElementReferenceException:
                continue
            idx += 1
            ref = f"e{idx}"
            self._elements[ref] = el
            self.last_element_labels[ref] = f'{role} "{name}"'
            state = " [desabilitado]" if not enabled else ""
            rows.append(f'[{ref}] {role} "{name}"{state}')
        return rows

    def _describe_element(self, el: Any) -> tuple[str, str, bool]:
        if self.platform == "android":
            class_name = str(el.get_attribute("className") or "")
            clickable = (el.get_attribute("clickable") or "false") == "true"
            content_desc = str(el.get_attribute("contentDescription") or "")
            text = el.text or ""
            resource_id = str(el.get_attribute("resourceId") or "")
            enabled = (el.get_attribute("enabled") or "true") != "false"
            role = _android_role_for(class_name, clickable)
            name = (content_desc or text or resource_id.rsplit("/", 1)[-1])[:80]
            return role, name, enabled

        element_type = str(el.tag_name or "")
        label = str(el.get_attribute("label") or "")
        name_attr = str(el.get_attribute("name") or "")
        value_attr = str(el.get_attribute("value") or "")
        enabled = (el.get_attribute("enabled") or "true") != "false"
        role = _ios_role_for(element_type)
        name = (label or name_attr or value_attr)[:80]
        return role, name, enabled

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
        # Um toque pode disparar uma transição assíncrona (chamada de rede,
        # animação de tela) que ainda não terminou no instante em que
        # tiramos o snapshot logo em seguida — sem essa pausa, o snapshot
        # captura a tela ANTIGA e quem chamou (em especial o modo "explore",
        # que decide sozinho e não tem um humano pra inserir um
        # mobile_wait_for depois de um login/submit) conclui erradamente
        # que a ação não teve efeito. Achado ao vivo: exploração declarou
        # "CONCLUIDO" após tocar em "acessar" (login) sem ver mudança,
        # enquanto o vídeo da sessão mostra a navegação pra tela seguinte
        # completando alguns segundos depois, já fora da janela observada.
        await asyncio.sleep(_ACTION_SETTLE_SECONDS)
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
            if self.platform == "android":
                await asyncio.to_thread(
                    self.driver.execute_script, "mobile: longClickGesture", {"elementId": el.id, "duration": 1000}
                )
            else:
                await asyncio.to_thread(
                    self.driver.execute_script, "mobile: touchAndHold", {"elementId": el.id, "duration": 1.0}
                )
        except StaleElementReferenceException as e:
            raise MobileToolError(f"Ref {ref} ficou obsoleta (a tela mudou) — tire um novo snapshot.") from e
        return f"Toque longo em {ref}.\n\n" + await self.snapshot_text()

    async def swipe(self, direction: str) -> str:
        # Gesto genérico via W3C Actions puro (pointer input) — não depende
        # de um comando "mobile: X" nomeado por plataforma, então funciona
        # igual em Android e iOS.
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
        try:
            if self.platform == "android":
                await asyncio.to_thread(self._android_scroll_to_sync, escaped)
            else:
                await asyncio.to_thread(self._ios_scroll_to_sync, escaped)
        except (NoSuchElementException, WebDriverException) as e:
            raise MobileToolError(f'Não consegui rolar até um texto contendo "{text}": {e}') from e
        return f'Rolou até "{text}".\n\n' + await self.snapshot_text()

    def _android_scroll_to_sync(self, text: str) -> None:
        selector = (
            'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView('
            f'new UiSelector().textContains("{text}"))'
        )
        self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector)

    def _ios_scroll_to_sync(self, text: str, max_attempts: int = 6) -> None:
        # XCUITest não tem um "scroll até achar" nativo como o UiScrollable
        # do Android — `mobile: scroll` faz UM scroll por chamada, então
        # repete até o texto aparecer ou esgotar as tentativas.
        predicate = f"name CONTAINS '{text}' OR label CONTAINS '{text}'"
        locator = f'**/XCUIElementTypeAny[`{predicate}`]'
        for _ in range(max_attempts):
            if self.driver.find_elements(AppiumBy.IOS_CLASS_CHAIN, locator):
                return
            self.driver.execute_script("mobile: scroll", {"direction": "down"})
        # última tentativa — deixa a NoSuchElementException real propagar
        # com a mensagem padrão do Selenium.
        self.driver.find_element(AppiumBy.IOS_CLASS_CHAIN, locator)

    async def press_back(self) -> str:
        if self.platform != "android":
            raise MobileToolError(
                "iOS não tem um botão de voltar de hardware/sistema — toque no botão de voltar "
                "visível na tela (veja o snapshot) em vez de usar mobile_press_back."
            )
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
        if self.platform == "android":
            xpath = f'//*[contains(@text,"{escaped}") or contains(@content-desc,"{escaped}")]'
        else:
            xpath = f'//*[contains(@name,"{escaped}") or contains(@label,"{escaped}") or contains(@value,"{escaped}")]'
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
        """Pressiona o botão de voltar do sistema (só Android — no iOS não
        existe; toque no botão de voltar visível na tela)."""
        try:
            return await session.press_back()
        except MobileToolError as e:
            return str(e)

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


def build_explore_mobile_tools(session: MobileSession) -> list:
    """Mesma fábrica de `build_mobile_tools`, com um guardrail EM CÓDIGO
    aplicado antes de tocar — obrigatório só no modo "explore" (o agente
    escolhe as próprias ações, sem um passo determinado por um humano pra
    seguir): `mobile_tap` recusa um alvo cujo nome/role bate no denylist de
    ações perigosas (ver src/tools/explore_guardrails.py). Mobile não tem
    uma tool de navegação
    por URL (não existe endereço fora do app sob teste), então o guardrail
    de "mesma origem" do lado web não se aplica aqui — o risco equivalente
    (diálogos nativos de permissão/compra) fica a cargo do prompt de
    exploração, documentado como lacuna conhecida."""

    @tool
    async def mobile_snapshot() -> str:
        """Lê a tela atual do app: lista os elementos visíveis (botões,
        campos, textos) com uma ref curta (ex.: [e3] button "Entrar")."""
        return await session.snapshot_text()

    @tool
    async def mobile_tap(ref: str) -> str:
        """Toca no elemento identificado pela ref. Recusa alvos que pareçam
        iniciar uma ação com efeito real (comprar, excluir, cancelar,
        enviar)."""
        if is_dangerous_action(session.element_label(ref)):
            return DANGEROUS_ACTION_REFUSAL
        try:
            return await session.tap(ref)
        except MobileToolError as e:
            return str(e)

    @tool
    async def mobile_type(ref: str, text: str) -> str:
        """Digita texto num campo identificado pela ref. Use valores
        obviamente fictícios (ex.: explorer+argus@example.com) — nunca dados
        reais."""
        try:
            return await session.type_text(ref, text)
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
        informado."""
        try:
            return await session.scroll_to(text)
        except MobileToolError as e:
            return str(e)

    @tool
    async def mobile_press_back() -> str:
        """Pressiona o botão de voltar do sistema (só Android)."""
        try:
            return await session.press_back()
        except MobileToolError as e:
            return str(e)

    @tool
    async def mobile_wait_for(text: str, timeout_ms: int = 8000) -> str:
        """Espera até um texto aparecer visível na tela (timeout em ms,
        default 8000)."""
        try:
            return await session.wait_for(text, timeout_ms)
        except MobileToolError as e:
            return str(e)

    return [mobile_snapshot, mobile_tap, mobile_type, mobile_swipe, mobile_scroll_to, mobile_press_back, mobile_wait_for]
