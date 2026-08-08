"""Argus Agent — subgrafo executor: um passo Gherkin por invocação.

Usa `langchain.agents.create_agent` (agente ReAct do LangGraph) — é aqui, no
loop de tool-calling de um único passo, que o LangGraph realmente ganha seu
lugar nesta arquitetura (vs. a orquestração de fases da run, que é controle
de fluxo Python comum em src/agent/nodes.py). Cada passo é uma invocação
NOVA do agente (mensagens vazias, só o prompt do passo) — contexto zerado
por passo, por design: mantém os tokens baixos e evita que o histórico de um
passo anterior confunda a decisão do atual. Continuidade entre passos vem só
do resumo curto (`history`) embutido no prompt, não do histórico de
mensagens do LLM.

Recebe `tools` já construída pelo chamador (nodes.py) em vez de montar a
lista sozinho a partir de uma sessão — mantém este módulo agnóstico de
plataforma (web via Playwright, android via Appium usam a mesma engine de
tool-calling, só a lista de tools muda; ver build_web_tools/
build_mobile_tools)."""
import logging
import re
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from src.agent.prompts import PERSONA_SYSTEM_PROMPT, build_step_prompt

logger = logging.getLogger(__name__)

_RESULT_RE = re.compile(r"RESULTADO:\s*(PASSOU|FALHOU)\s*(?:—|-)?\s*(.*)", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class StepOutcome:
    """`tokens_in`/`tokens_out` somam o `usage_metadata` de TODAS as
    chamadas de LLM do loop ReAct deste passo (uma invocação pode fazer
    várias idas e vindas de tool-calling antes do veredito final) — zero
    nos caminhos de erro que nunca chegam a rodar o agente com sucesso
    (limite de recursão, provider fora do ar): não dá pra recuperar uso
    parcial de dentro da exceção do LangGraph."""

    passed: bool
    message: str
    tokens_in: int = 0
    tokens_out: int = 0

# Mensagem canônica que o agente ReAct do LangGraph injeta quando o
# contador interno de passos restantes (derivado do `recursion_limit`
# passado em config) chega a zero — um limite "soft" que para o loop sem
# levantar exceção. `GraphRecursionError` (capturado abaixo) é o limite
# "hard" do motor do grafo, que na prática quase nunca dispara primeiro
# (os dois usam o mesmo `recursion_limit`), mas fica como rede de segurança.
_STEPS_EXHAUSTED_MARKER = "need more steps"

DEFAULT_MAX_ITERATIONS = 8


async def run_step(
    *,
    tools: list,
    chat_model: BaseChatModel,
    keyword: str,
    step_text: str,
    scenario_name: str,
    history: list[str],
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> StepOutcome:
    """Executa um passo via um agente ReAct fresco. Nunca levanta — qualquer
    falha (erro de ferramenta/provider, loop do agente, resposta sem
    veredito claro) vira `StepOutcome(passed=False, ...)`."""
    prompt = build_step_prompt(keyword=keyword, step_text=step_text, scenario_name=scenario_name, history=history)

    try:
        agent = create_agent(
            model=chat_model,
            tools=tools,
            system_prompt=PERSONA_SYSTEM_PROMPT.format(max_iterations=max_iterations),
        )
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": max_iterations * 2 + 6},
        )
    except GraphRecursionError:
        return StepOutcome(
            False, f"O agente excedeu o limite de {max_iterations} chamadas de ferramenta para este passo (loop do agente)."
        )
    except Exception as e:
        logger.warning("Falha ao executar passo via LLM: %s", e)
        return StepOutcome(False, f"Erro ao executar o passo: {e}")

    tokens_in, tokens_out = _sum_usage(result)
    final_content = _final_text(result)
    if _STEPS_EXHAUSTED_MARKER in final_content.lower():
        return StepOutcome(
            False, f"O agente excedeu o limite de {max_iterations} chamadas de ferramenta para este passo (loop do agente).",
            tokens_in, tokens_out,
        )

    match = _RESULT_RE.search(final_content)
    if not match:
        return StepOutcome(
            False, f"O agente não declarou um veredito claro. Última resposta: {final_content[:300]}", tokens_in, tokens_out
        )

    passed = match.group(1).upper() == "PASSOU"
    reason = match.group(2).strip() or final_content.strip()
    return StepOutcome(passed, reason, tokens_in, tokens_out)


def _final_text(agent_result: dict) -> str:
    messages = agent_result.get("messages", [])
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content
    return ""


def _sum_usage(agent_result: dict) -> tuple[int, int]:
    """Soma `usage_metadata` (campo normalizado do LangChain, presente em
    AIMessage de qualquer provider) de todas as chamadas de LLM do loop
    ReAct deste passo — pode ser mais de uma (várias idas e vindas de
    tool-calling antes do veredito final)."""
    tokens_in = tokens_out = 0
    for message in agent_result.get("messages", []):
        usage = getattr(message, "usage_metadata", None)
        if usage:
            tokens_in += usage.get("input_tokens") or 0
            tokens_out += usage.get("output_tokens") or 0
    return tokens_in, tokens_out
