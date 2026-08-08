"""Argus Agent — tools Playwright para o executor do agente web.

`WebSession.snapshot_text()` é a tool central: em vez de mandar screenshots
(caro em tokens e ambíguo pra um LLM apontar coordenadas), varre o DOM via
JS e devolve uma lista textual compacta de elementos interativos visíveis,
cada um com uma ref curta (`e3`) — ações (`click`/`fill`/...) então miram
por ref, não por seletor CSS longo nem coordenada de tela. Cada chamada de
snapshot revarre e reatribui as refs (o DOM pode ter mudado), então o
prompt do executor sempre pede pro LLM olhar o snapshot mais recente antes
de agir."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from playwright.async_api import Page

_SNAPSHOT_JS = """
() => {
  const results = [];
  let idx = 0;
  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const style = window.getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none';
  };
  const selector = 'a[href], button, input, select, textarea, ' +
    '[role="button"], [role="link"], [role="textbox"], [role="checkbox"], ' +
    '[role="radio"], [role="combobox"], [onclick], [tabindex]';
  document.querySelectorAll(selector).forEach((el) => {
    if (!isVisible(el)) return;
    idx += 1;
    const ref = 'e' + idx;
    el.setAttribute('data-argus-ref', ref);
    const tag = el.tagName.toLowerCase();
    let role = el.getAttribute('role');
    if (!role) {
      if (tag === 'a') role = 'link';
      else if (tag === 'button') role = 'button';
      else if (tag === 'input') role = el.getAttribute('type') || 'textbox';
      else if (tag === 'select') role = 'combobox';
      else if (tag === 'textarea') role = 'textbox';
      else role = 'generic';
    }
    const name = el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
      (el.innerText ? el.innerText.trim().slice(0, 80) : '') ||
      el.getAttribute('value') || el.getAttribute('name') || '';
    results.push({ ref, role, name, disabled: !!el.disabled });
  });
  return results;
}
"""


class WebToolError(RuntimeError):
    """Uma tool Playwright falhou de um jeito que o LLM deve ver e reagir
    (ref inexistente, timeout de espera) — nunca deixado propagar cru: vira
    texto de erro devolvido como resultado da tool."""


@dataclass
class WebSession:
    """Estado vivo de uma run web: página do Playwright + onde salvar
    screenshots. Não é serializável (não entra no estado do LangGraph) —
    vive num registro em memória por run_id, ver src/agent/nodes.py."""

    page: Page
    run_id: str
    artifacts_dir: Path
    scenario_position: int = field(default=0)
    step_position: int = field(default=0)

    def set_step_context(self, scenario_position: int, step_position: int) -> None:
        self.scenario_position = scenario_position
        self.step_position = step_position

    async def snapshot_text(self) -> str:
        elements: list[dict[str, Any]] = await self.page.evaluate(_SNAPSHOT_JS)
        url = self.page.url
        title = await self.page.title()
        lines = [f"URL: {url}", f'Título: "{title}"', ""]
        if not elements:
            lines.append("(nenhum elemento interativo visível)")
        for el in elements:
            state = " [desabilitado]" if el.get("disabled") else ""
            lines.append(f'[{el["ref"]}] {el["role"]} "{el["name"]}"{state}')
        return "\n".join(lines)

    def _locator(self, ref: str):
        return self.page.locator(f'[data-argus-ref="{ref}"]')

    async def _require_locator(self, ref: str):
        locator = self._locator(ref)
        if await locator.count() == 0:
            raise WebToolError(f"Ref {ref} não encontrada — tire um novo snapshot antes de agir.")
        return locator

    async def navigate(self, url: str) -> str:
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return await self.snapshot_text()

    async def click(self, ref: str) -> str:
        locator = await self._require_locator(ref)
        await locator.click(timeout=5_000)
        return f"Clicou em {ref}.\n\n" + await self.snapshot_text()

    async def fill(self, ref: str, text: str) -> str:
        locator = await self._require_locator(ref)
        await locator.fill(text, timeout=5_000)
        return f"Preencheu {ref} com o valor informado."

    async def select(self, ref: str, value: str) -> str:
        locator = await self._require_locator(ref)
        await locator.select_option(value, timeout=5_000)
        return f"Selecionou \"{value}\" em {ref}."

    async def press_key(self, key: str) -> str:
        await self.page.keyboard.press(key)
        return f"Pressionou a tecla {key}.\n\n" + await self.snapshot_text()

    async def hover(self, ref: str) -> str:
        locator = await self._require_locator(ref)
        await locator.hover(timeout=5_000)
        return f"Passou o mouse sobre {ref}."

    async def scroll(self, direction: str) -> str:
        delta = 600 if direction == "down" else -600
        await self.page.mouse.wheel(0, delta)
        return f"Rolou a página para {direction}."

    async def wait_for(self, text: str, timeout_ms: int = 8_000) -> str:
        try:
            await self.page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout_ms)
            return f'Texto "{text}" apareceu.\n\n' + await self.snapshot_text()
        except Exception as e:
            raise WebToolError(f'Texto "{text}" não apareceu em {timeout_ms}ms: {e}') from e

    async def back(self) -> str:
        await self.page.go_back(wait_until="domcontentloaded", timeout=15_000)
        return await self.snapshot_text()

    async def get_url(self) -> str:
        return self.page.url

    async def screenshot(self, label: str) -> Path:
        screenshots_dir = self.artifacts_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label) or "evidencia"
        path = screenshots_dir / f"{self.scenario_position}_{self.step_position}_{safe_label}.png"
        await self.page.screenshot(path=str(path))
        return path


def build_web_tools(session: WebSession) -> list:
    """Fábrica de tools LangChain fechadas sobre uma WebSession viva — uma
    lista nova por passo/cenário garante que a sessão sempre é a atual
    (o navegador pode ter navegado entre passos)."""

    @tool
    async def browser_navigate(url: str) -> str:
        """Navega para uma URL e devolve o snapshot da página resultante."""
        try:
            return await session.navigate(url)
        except Exception as e:
            return f"Erro ao navegar: {e}"

    @tool
    async def browser_snapshot() -> str:
        """Tira um snapshot de acessibilidade da página atual: lista os
        elementos interativos visíveis com uma ref curta (ex.: [e3] button
        "Entrar"). Use antes de clicar/preencher para saber as refs atuais —
        elas mudam a cada navegação ou mudança relevante na página."""
        return await session.snapshot_text()

    @tool
    async def browser_click(ref: str) -> str:
        """Clica no elemento identificado pela ref (ex.: "e3"), obtida de um
        browser_snapshot anterior."""
        try:
            return await session.click(ref)
        except WebToolError as e:
            return str(e)

    @tool
    async def browser_fill(ref: str, text: str) -> str:
        """Preenche um campo de texto/senha identificado pela ref com o
        valor informado."""
        try:
            return await session.fill(ref, text)
        except WebToolError as e:
            return str(e)

    @tool
    async def browser_select(ref: str, value: str) -> str:
        """Seleciona uma opção (pelo value do <option>) num <select>
        identificado pela ref."""
        try:
            return await session.select(ref, value)
        except WebToolError as e:
            return str(e)

    @tool
    async def browser_press_key(key: str) -> str:
        """Pressiona uma tecla do teclado (ex.: "Enter", "Escape", "Tab")."""
        return await session.press_key(key)

    @tool
    async def browser_hover(ref: str) -> str:
        """Passa o mouse sobre o elemento identificado pela ref (útil para
        menus/tooltips que só aparecem no hover)."""
        try:
            return await session.hover(ref)
        except WebToolError as e:
            return str(e)

    @tool
    async def browser_scroll(direction: str) -> str:
        """Rola a página na direção indicada ("down" ou "up")."""
        return await session.scroll(direction)

    @tool
    async def browser_wait_for(text: str, timeout_ms: int = 8000) -> str:
        """Espera até um texto aparecer visível na página (timeout em ms,
        default 8000). Use antes de declarar que um passo "Then"/"Então"
        falhou — a UI pode estar carregando."""
        try:
            return await session.wait_for(text, timeout_ms)
        except WebToolError as e:
            return str(e)

    @tool
    async def browser_screenshot(label: str) -> str:
        """Salva uma screenshot da tela atual como evidência, rotulada com
        `label`. Use para documentar uma verificação importante."""
        path = await session.screenshot(label)
        return f"Screenshot salva: {path.name}"

    @tool
    async def browser_back() -> str:
        """Volta para a página anterior no histórico de navegação."""
        return await session.back()

    @tool
    async def browser_get_url() -> str:
        """Retorna a URL atual da página."""
        return await session.get_url()

    return [
        browser_navigate,
        browser_snapshot,
        browser_click,
        browser_fill,
        browser_select,
        browser_press_key,
        browser_hover,
        browser_scroll,
        browser_wait_for,
        browser_screenshot,
        browser_back,
        browser_get_url,
    ]
