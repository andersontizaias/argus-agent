"""Testes do executor (subgrafo ReAct por passo).

Usa um chat model "roteirizado" (fake, determinístico) em vez de um LLM
real: valida a integração de verdade com `create_react_agent` + as tools
Playwright reais (rodando contra a página local de fixture), sem custo nem
flakiness de rede."""
from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from playwright.async_api import async_playwright
from pydantic import PrivateAttr

from src.agent.executor import run_step
from src.tools.web import WebSession

FIXTURE_URL = f"file://{Path(__file__).parent / 'fixtures' / 'login.html'}"

pytestmark = pytest.mark.anyio


class ScriptedChatModel(BaseChatModel):
    """Devolve uma sequência fixa de AIMessage — uma por chamada — pra
    simular um LLM real fazendo tool-calling sem custo/rede."""

    responses: list[AIMessage]
    _index: int = PrivateAttr(default=0)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        msg = self.responses[self._index]
        self._index += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"


def _tool_call_message(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


@pytest.fixture
async def session(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(FIXTURE_URL)
        yield WebSession(page=page, run_id="test-run", artifacts_dir=tmp_path)
        await browser.close()


async def test_run_step_executes_real_tools_and_reports_pass(session):
    model = ScriptedChatModel(responses=[
        _tool_call_message("browser_snapshot", {}, "call-1"),
        _tool_call_message("browser_fill", {"ref": "e1", "text": "standard_user"}, "call-2"),
        AIMessage(content="RESULTADO: PASSOU — usuário preenchido com sucesso"),
    ])

    passed, message = await run_step(
        session=session, chat_model=model, keyword="Quando",
        step_text='preencho usuário "standard_user"', scenario_name="Login válido", history=[],
    )

    assert passed is True
    assert "sucesso" in message
    assert await session.page.input_value('[data-argus-ref="e1"]') == "standard_user"


async def test_run_step_reports_failure_from_llm_verdict(session):
    model = ScriptedChatModel(responses=[AIMessage(content="RESULTADO: FALHOU — elemento não encontrado")])

    passed, message = await run_step(
        session=session, chat_model=model, keyword="Então",
        step_text="vejo a lista de produtos", scenario_name="Login inválido", history=[],
    )

    assert passed is False
    assert "elemento não encontrado" in message


async def test_run_step_no_clear_verdict_counts_as_failure(session):
    model = ScriptedChatModel(responses=[AIMessage(content="Cliquei no botão de login.")])

    passed, message = await run_step(
        session=session, chat_model=model, keyword="Quando",
        step_text="clico em entrar", scenario_name="Login válido", history=[],
    )

    assert passed is False
    assert "veredito claro" in message


async def test_run_step_recursion_limit_counts_as_failure(session):
    # Sempre pede snapshot de novo — nunca declara um RESULTADO — força o
    # agente a estourar o limite de iterações.
    infinite_snapshots = [_tool_call_message("browser_snapshot", {}, f"call-{i}") for i in range(20)]
    model = ScriptedChatModel(responses=infinite_snapshots)

    passed, message = await run_step(
        session=session, chat_model=model, keyword="Quando",
        step_text="clico em entrar", scenario_name="Login válido", history=[], max_iterations=2,
    )

    assert passed is False
    assert "loop do agente" in message


async def test_run_step_model_error_counts_as_failure(session):
    class BrokenModel(ScriptedChatModel):
        def bind_tools(self, tools, **kwargs):
            raise RuntimeError("provider indisponível")

    model = BrokenModel(responses=[])
    passed, message = await run_step(
        session=session, chat_model=model, keyword="Quando",
        step_text="clico em entrar", scenario_name="Login válido", history=[],
    )

    assert passed is False
    assert "Erro ao executar o passo" in message
