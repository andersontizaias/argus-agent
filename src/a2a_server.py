"""Argus Agent — servidor A2A (rota `/a2a` + AgentCard em
`/.well-known/agent-card.json`). Fachada fina sobre `run_service` — mesmo
princípio do MCP (`src/mcp_server.py`): nenhuma lógica de validação/negócio
duplicada aqui, só tradução pro modelo de eventos/task do protocolo A2A.

A skill `execute_qa_test` espera uma Message com UMA Part de dados (JSON)
no MESMO formato aceito pela tool `run_test` do MCP (`platform`,
`bdd_script`, `app_url`, `binary_url`, `binary_auth_secret`, `test_data`,
`llm_provider`, `llm_model`) — um único contrato de parâmetros entre as
duas superfícies de integração, em vez de inventar um novo formato de
texto livre pra cada uma."""
from __future__ import annotations

import asyncio
import json
import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Part,
)
from a2a.utils import DEFAULT_RPC_URL, TransportProtocol

from src import run_service
from src.settings import HOST, PORT, VERSION

TERMINAL_STATUSES = run_service.TERMINAL_STATUSES
POLL_SECONDS = 2.0
DEFAULT_WAIT_TIMEOUT_SECONDS = 600

RUN_PARAM_KEYS = (
    "platform", "bdd_script", "app_url", "binary_url", "binary_auth_secret",
    "test_data", "llm_provider", "llm_model",
)


def build_agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="Argus Agent",
        description=(
            "Agente de QA autônomo que executa testes end-to-end (web, Android, iOS) a "
            "partir de um script BDD (Gherkin) e massa de testes, dirigindo a aplicação de "
            "verdade e produzindo um relatório com evidências (screenshots por passo)."
        ),
        version=VERSION,
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}{DEFAULT_RPC_URL}",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version="1.0",
            ),
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["application/json", "text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="execute_qa_test",
                name="Executar teste de QA",
                description=(
                    "Cria e acompanha uma execução de teste QA a partir de um script BDD "
                    "(Gherkin). Envie os parâmetros (platform, bdd_script, app_url ou "
                    "binary_url, test_data, llm_provider, llm_model) como uma Part de dados "
                    "(JSON) na mensagem — mesmo formato da tool MCP `run_test`."
                ),
                tags=["qa", "teste", "bdd", "e2e"],
                examples=[
                    (
                        '{"platform": "web", "app_url": "https://example.com", '
                        '"bdd_script": "# language: pt\\nFuncionalidade: X\\n  Cenario: Y\\n    Dado algo"}'
                    ),
                ],
                input_modes=["application/json"],
                output_modes=["text/plain"],
            ),
        ],
    )


def _extract_run_params(context: RequestContext) -> dict:
    """Procura uma Part de dados na mensagem; se não achar, tenta interpretar
    a primeira Part de texto como JSON (cliente simples que só sabe mandar
    texto). Erra com uma mensagem clara se não conseguir nenhum dos dois."""
    message = context.message
    if message is not None:
        for part in message.parts:
            # `Part.data` é um `google.protobuf.Value` (não um Struct
            # diretamente) — só vira dict de verdade quando o valor
            # envolvido É um objeto JSON (struct_value), não uma lista/
            # string/número solto.
            if part.HasField("data") and part.data.WhichOneof("kind") == "struct_value":
                data = {k: v for k, v in part.data.struct_value.items() if k in RUN_PARAM_KEYS}
                if data:
                    return data

    text = context.get_user_input().strip()
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise run_service.RunServiceError(
                "Não encontrei uma Part de dados com os parâmetros da run, e o texto da "
                f"mensagem não é JSON válido: {e}"
            ) from e
        if isinstance(parsed, dict):
            return {k: v for k, v in parsed.items() if k in RUN_PARAM_KEYS}

    raise run_service.RunServiceError(
        "Nenhum parâmetro de execução encontrado — envie uma Part de dados (ou texto JSON) "
        "com platform/bdd_script/app_url/binary_url/etc., igual aos argumentos da tool MCP "
        "run_test."
    )


class ArgusAgentExecutor(AgentExecutor):
    """Cria uma run via `run_service.create_run` e espera até um status
    terminal, publicando o progresso como eventos de task A2A (submitted →
    working → completed/failed)."""

    def __init__(self) -> None:
        # Mapeia task_id (gerado pelo framework A2A) -> run_id (Argus) —
        # necessário só pra `cancel()` conseguir achar qual run cancelar.
        # Em memória (mesmo espírito do `_SESSIONS` de src/agent/nodes.py):
        # um restart do processo perde o mapeamento, não o progresso da run
        # (que já está no banco).
        self._task_to_run: dict[str, str] = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        from a2a.server.tasks.task_updater import TaskUpdater

        task_id, context_id = _require_ids(context)
        updater = TaskUpdater(event_queue, task_id, context_id)
        await updater.submit()

        try:
            params = _extract_run_params(context)
            run = run_service.create_run(**params)
        except (run_service.RunServiceError, TypeError) as e:
            await updater.failed(updater.new_agent_message([Part(text=str(e))]))
            return

        self._task_to_run[task_id] = run.id
        await updater.start_work(updater.new_agent_message([Part(text=f"Run {run.id} criada, executando...")]))

        summary = await _wait_for_terminal(run.id)

        report_text = f"Run {run.id} terminou com status {summary['status']}."
        if summary.get("error"):
            report_text += f" Erro: {summary['error']}"
        message = updater.new_agent_message([Part(text=report_text)])
        if summary["status"] == "passed":
            await updater.complete(message)
        else:
            await updater.failed(message)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        from a2a.server.tasks.task_updater import TaskUpdater

        task_id, context_id = _require_ids(context)
        run_id = self._task_to_run.get(task_id)
        if run_id:
            try:
                run_service.request_cancel(run_id)
            except (run_service.RunNotFoundError, run_service.RunServiceError):
                pass  # já terminou ou não existe — segue com o cancelamento da task mesmo assim
        updater = TaskUpdater(event_queue, task_id, context_id)
        await updater.cancel()


def _require_ids(context: RequestContext) -> tuple[str, str]:
    """task_id/context_id vêm tipados como opcionais na assinatura do SDK,
    mas o `DefaultRequestHandler` sempre os popula antes de chamar
    `execute`/`cancel` (cria a task primeiro) — isso aqui é só pra
    satisfazer o mypy com uma falha clara, nunca esperado disparar."""
    if not context.task_id or not context.context_id:
        raise RuntimeError("RequestContext sem task_id/context_id — inesperado, é o framework A2A quem os popula.")
    return context.task_id, context.context_id


async def _wait_for_terminal(run_id: str, *, timeout_seconds: int = DEFAULT_WAIT_TIMEOUT_SECONDS) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while True:
        summary = run_service.get_run_summary(run_id)
        if summary["status"] in TERMINAL_STATUSES:
            return summary
        if time.monotonic() > deadline:
            return summary
        await asyncio.sleep(POLL_SECONDS)


def build_request_handler(agent_card: AgentCard) -> DefaultRequestHandler:
    return DefaultRequestHandler(
        agent_executor=ArgusAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )


def default_base_url() -> str:
    return f"http://{HOST}:{PORT}/a2a"
