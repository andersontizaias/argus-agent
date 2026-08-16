"""Argus Agent — grafo principal de uma run (fases fixas, com checkpointing).

`parse_bdd → provision_target → run_scenarios → teardown_target →
compile_report`, com desvio direto pro relatório se `parse_bdd` ou
`provision_target` falharem (nesses casos não há nada pra executar/
desprovisionar — exceto `provision_target`, que pode ter deixado um
navegador parcialmente aberto e por isso ainda passa por `teardown_target`).

Runs `mode="explore"` (ver PLANO — agente navega sozinho, sem BDD de
entrada) desviam pra `explore_app` em vez de `run_scenarios` logo depois de
`provision_target` — mesmo provisionamento/teardown/relatório, só o meio
muda. `parse_bdd` já sabe pular a si mesmo pra esse modo (nada pra
parsear), então a rota de entrada não precisa mudar.

Checkpointing via `AsyncSqliteSaver` (thread_id = run_id): permite retomar a
posição no grafo após uma falha transitória dentro do mesmo processo. Não é
o mecanismo primário de resiliência a crash do worker — esse é o banco (ver
o docstring de src/agent/state.py); o checkpoint é uma camada extra."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph

from src import store
from src.agent import nodes
from src.agent.state import RunState
from src.settings import checkpoints_db_path


def _route_after(state: RunState) -> str:
    return "end" if state.get("error") else "continue"


def _route_after_provision(state: RunState) -> str:
    """Erro em `provision_target` sempre vai pro teardown (pode ter deixado
    um navegador/emulador parcialmente aberto), igual antes. Sem erro,
    ramifica por `run.mode` — "explore" pula `run_scenarios` inteiramente
    (não há cenários: `parse_bdd` já pulou a si mesmo pra esse modo)."""
    if state.get("error"):
        return "end"
    run = store.get_run(state["run_id"])
    return "explore" if run and run.mode == "explore" else "execute"


def build_graph() -> StateGraph:
    graph = StateGraph(RunState)
    graph.add_node("parse_bdd", nodes.parse_bdd)
    graph.add_node("provision_target", nodes.provision_target)
    graph.add_node("run_scenarios", nodes.run_scenarios)
    graph.add_node("explore_app", nodes.explore_app)
    graph.add_node("teardown_target", nodes.teardown_target)
    graph.add_node("compile_report", nodes.compile_report)

    graph.set_entry_point("parse_bdd")
    graph.add_conditional_edges("parse_bdd", _route_after, {"continue": "provision_target", "end": "compile_report"})
    graph.add_conditional_edges(
        "provision_target", _route_after_provision,
        {"execute": "run_scenarios", "explore": "explore_app", "end": "teardown_target"},
    )
    graph.add_edge("run_scenarios", "teardown_target")
    graph.add_edge("explore_app", "teardown_target")
    graph.add_edge("teardown_target", "compile_report")
    graph.add_edge("compile_report", END)
    return graph


@asynccontextmanager
async def _checkpointer() -> AsyncIterator[AsyncSqliteSaver]:
    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_db_path())) as saver:
        yield saver


async def run_graph(run_id: str) -> None:
    """Compila e executa o grafo para uma run até o fim (ou até um erro
    irrecuperável, já registrado no banco pelos próprios nós)."""
    async with _checkpointer() as checkpointer:
        compiled = build_graph().compile(checkpointer=checkpointer)
        await compiled.ainvoke(
            {"run_id": run_id},
            config={"configurable": {"thread_id": run_id}, "recursion_limit": 25},
        )
