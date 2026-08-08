"""Argus Agent — estado do StateGraph principal.

Deliberadamente mínimo: só `run_id` (e `error`, setado por um nó que falhou
de forma irrecuperável). Cenários/passos/status vivem no banco
(`src.store`), não no estado do grafo — isso mantém o checkpoint pequeno e
faz do banco a única fonte de verdade tanto para o relatório quanto para
retomar uma run interrompida (um worker que reinicia re-invoca o grafo pelo
mesmo `thread_id` e os nós redescobrem o progresso consultando o banco, não
o checkpoint)."""
from typing import TypedDict


class RunState(TypedDict, total=False):
    run_id: str
    error: str | None
