"""Argus Agent — servidor MCP (Streamable HTTP), montado em `/mcp` no mesmo
app FastAPI que serve a API REST e a UI (ver src/main.py). Fachada fina
sobre `run_service` — as tools aqui não reimplementam nenhuma validação ou
regra de negócio, só traduzem o resultado pro formato de retorno de uma
tool MCP (dict; erros viram `{"error": "..."}` em vez de levantar, já que
não há um código de status HTTP pra mapear aqui). A2A (fase futura) segue o
mesmo princípio."""
import asyncio
import time

from mcp.server.mcpserver import MCPServer

from src import run_service
from src.settings import VERSION

TERMINAL_STATUSES = run_service.TERMINAL_STATUSES
DEFAULT_WAIT_POLL_SECONDS = 2.0
DEFAULT_WAIT_TIMEOUT_SECONDS = 300

mcp_server = MCPServer(
    name="argus-agent",
    version=VERSION,
    instructions=(
        "Argus Agent executa testes de QA end-to-end (web, Android, iOS) a partir de um "
        "script BDD (Gherkin) e massa de testes, dirigindo a aplicação de verdade (browser "
        "real via Playwright, emulador/simulador real via Appium) e produzindo um relatório "
        "com evidências (screenshots por passo). Use run_test para criar uma execução — "
        "com wait=true ela só retorna depois da run terminar (passed/failed/error/canceled)."
    ),
)


@mcp_server.tool()
async def run_test(
    platform: str,
    bdd_script: str,
    app_url: str | None = None,
    binary_url: str | None = None,
    binary_auth_secret: str | None = None,
    test_data: dict[str, str] | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    wait: bool = False,
    wait_timeout_seconds: int = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> dict:
    """Cria uma execução de teste QA a partir de um script BDD (Gherkin).

    platform: "web" (exige app_url) | "android" ou "ios" (exigem binary_url
    apontando pro .apk / .zip de um build de simulador). binary_auth_secret
    é o NOME de um secret já cadastrado no Argus (não o valor). test_data é
    o dicionário de valores referenciados como <placeholder> nos passos do
    BDD. llm_provider/llm_model usam o default configurado no Argus se
    omitidos. Se wait=True, espera a run chegar num status terminal antes
    de retornar (até wait_timeout_seconds, default 300s) — se o timeout
    estourar antes, retorna o status atual mesmo assim (normalmente ainda
    "running"), sem levantar erro.
    """
    try:
        run = run_service.create_run(
            platform=platform,
            bdd_script=bdd_script,
            app_url=app_url,
            binary_url=binary_url,
            binary_auth_secret=binary_auth_secret,
            test_data=test_data,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
    except run_service.RunServiceError as e:
        return {"error": str(e)}

    if wait:
        await _wait_for_terminal_status(run.id, timeout_seconds=wait_timeout_seconds)

    return run_service.get_run_summary(run.id)


@mcp_server.tool()
async def get_run_status(run_id: str) -> dict:
    """Consulta o status atual de uma execução pelo id (queued/provisioning/
    running/passed/failed/error/canceled)."""
    try:
        return run_service.get_run_summary(run_id)
    except run_service.RunNotFoundError as e:
        return {"error": str(e)}


@mcp_server.tool()
async def get_report(run_id: str) -> dict:
    """Devolve o relatório completo (cenários, passos, status, evidências)
    de uma execução já terminada. Erra se a run ainda não terminou."""
    try:
        return run_service.get_report_dict(run_id)
    except (run_service.RunNotFoundError, run_service.RunServiceError) as e:
        return {"error": str(e)}


@mcp_server.tool()
async def list_runs(
    limit: int = 20, offset: int = 0, status: str | None = None, platform: str | None = None
) -> dict:
    """Lista execuções recentes (mais nova primeiro), com filtros opcionais
    por status e/ou plataforma."""
    return run_service.list_run_summaries(limit=limit, offset=offset, status=status, platform=platform)


@mcp_server.tool()
async def cancel_run(run_id: str) -> dict:
    """Solicita o cancelamento de uma execução em andamento. Erra se a run
    já tiver terminado ou não existir."""
    try:
        run_service.request_cancel(run_id)
    except (run_service.RunNotFoundError, run_service.RunServiceError) as e:
        return {"error": str(e)}
    return {"id": run_id, "cancel_requested": True}


async def _wait_for_terminal_status(run_id: str, *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        summary = run_service.get_run_summary(run_id)
        if summary["status"] in TERMINAL_STATUSES:
            return
        if time.monotonic() > deadline:
            return
        await asyncio.sleep(DEFAULT_WAIT_POLL_SECONDS)
