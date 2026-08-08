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

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from src.agent.prompts import PERSONA_SYSTEM_PROMPT, build_step_prompt

logger = logging.getLogger(__name__)

_RESULT_RE = re.compile(r"RESULTADO:\s*(PASSOU|FALHOU)\s*(?:—|-)?\s*(.*)", re.IGNORECASE | re.DOTALL)

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
) -> tuple[bool, str]:
    """Executa um passo via um agente ReAct fresco. Retorna (passou, mensagem).
    Nunca levanta — qualquer falha (erro de ferramenta/provider, loop do
    agente, resposta sem veredito claro) vira `(False, motivo)`."""
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
        return False, f"O agente excedeu o limite de {max_iterations} chamadas de ferramenta para este passo (loop do agente)."
    except Exception as e:
        logger.warning("Falha ao executar passo via LLM: %s", e)
        return False, f"Erro ao executar o passo: {e}"

    final_content = _final_text(result)
    if _STEPS_EXHAUSTED_MARKER in final_content.lower():
        return False, f"O agente excedeu o limite de {max_iterations} chamadas de ferramenta para este passo (loop do agente)."

    match = _RESULT_RE.search(final_content)
    if not match:
        return False, f"O agente não declarou um veredito claro. Última resposta: {final_content[:300]}"

    passed = match.group(1).upper() == "PASSOU"
    reason = match.group(2).strip() or final_content.strip()
    return passed, reason


def _final_text(agent_result: dict) -> str:
    messages = agent_result.get("messages", [])
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content
    return ""
