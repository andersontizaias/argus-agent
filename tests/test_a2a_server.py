"""Testes de src/a2a_server.py — extração de parâmetros da Message A2A,
forma do AgentCard, e o ArgusAgentExecutor (execute/cancel) com uma
EventQueue falsa (a real é async e não expõe leitura de volta, então uma
fake que só acumula os eventos publicados é suficiente e mais direta pra
testar a sequência de estados). Verificação com um client a2a-sdk de
verdade é manual, ver PLANO.md (F6)."""
import pytest
from google.protobuf.struct_pb2 import Struct, Value

from src import a2a_server as a2a_module
from src import store
from src.a2a_server import ArgusAgentExecutor, _extract_run_params, build_agent_card
from src.llm_providers import SUPPORTED_PROVIDERS
from src.user_secrets import set_secret_plain

pytestmark = pytest.mark.anyio

VALID_BDD = "# language: pt\nFuncionalidade: X\n  Cenario: Y\n    Dado algo\n"


@pytest.fixture
def configured_provider():
    provider = SUPPORTED_PROVIDERS[0]
    set_secret_plain(provider.secret_name, "sk-fake-key-not-used")
    store.set_setting("default_llm_provider", provider.id)
    store.set_setting("default_llm_model", provider.example_model)
    return provider


class _FakeEventQueue:
    def __init__(self):
        self.events: list = []

    async def enqueue_event(self, event):
        self.events.append(event)


def _make_context(*, data: dict | None = None, text: str | None = None, task_id="t1", context_id="c1"):
    from a2a.server.agent_execution.context import RequestContext
    from a2a.server.context import ServerCallContext
    from a2a.types import Message, Part, Role, SendMessageRequest

    parts = []
    if data is not None:
        struct = Struct()
        struct.update(data)
        parts.append(Part(data=Value(struct_value=struct)))
    if text is not None:
        parts.append(Part(text=text))
    message = Message(role=Role.ROLE_USER, message_id="m1", parts=parts)
    request = SendMessageRequest(message=message)
    return RequestContext(call_context=ServerCallContext(), request=request, task_id=task_id, context_id=context_id)


# ─── _extract_run_params ──────────────────────────────────────────────────


def test_extract_run_params_reads_data_part():
    context = _make_context(data={"platform": "web", "app_url": "https://x", "bdd_script": VALID_BDD})
    params = _extract_run_params(context)
    assert params["platform"] == "web"
    assert params["app_url"] == "https://x"


def test_extract_run_params_ignores_keys_outside_the_known_set():
    context = _make_context(data={"platform": "web", "bdd_script": VALID_BDD, "alien_field": "x"})
    params = _extract_run_params(context)
    assert "alien_field" not in params


def test_extract_run_params_falls_back_to_json_text():
    import json

    context = _make_context(text=json.dumps({"platform": "web", "bdd_script": VALID_BDD}))
    params = _extract_run_params(context)
    assert params["platform"] == "web"


def test_extract_run_params_raises_on_invalid_json_text():
    context = _make_context(text="isso não é json")
    with pytest.raises(a2a_module.run_service.RunServiceError, match="não é JSON válido"):
        _extract_run_params(context)


def test_extract_run_params_raises_when_nothing_found():
    context = _make_context()
    with pytest.raises(a2a_module.run_service.RunServiceError, match="Nenhum parâmetro"):
        _extract_run_params(context)


# ─── build_agent_card ──────────────────────────────────────────────────────


def test_build_agent_card_has_expected_shape():
    card = build_agent_card("http://127.0.0.1:8765/a2a")
    assert card.name == "Argus Agent"
    assert len(card.skills) == 1
    assert card.skills[0].id == "execute_qa_test"
    # Sem barra final — precisa bater exatamente com o `rpc_url` registrado
    # em main.py (`create_jsonrpc_routes(rpc_url="/a2a")`); regressão real:
    # uma barra final divergente aqui fazia o client a2a-sdk falhar com
    # "HTTP Error 307" (não segue redirect em streaming).
    assert card.supported_interfaces[0].url == "http://127.0.0.1:8765/a2a"
    assert card.supported_interfaces[0].protocol_binding == "JSONRPC"
    assert card.capabilities.streaming is True


# ─── ArgusAgentExecutor.execute ─────────────────────────────────────────────


def _status_states(queue: _FakeEventQueue) -> list:
    from a2a.types import TaskStatusUpdateEvent

    return [e.status.state for e in queue.events if isinstance(e, TaskStatusUpdateEvent)]


async def test_execute_enqueues_a_task_before_any_status_update(configured_provider, monkeypatch):
    # Regressão real: rodando um roundtrip de verdade com o client a2a-sdk,
    # o framework rejeitava a resposta com "Agent should enqueue Task
    # before TaskStatusUpdateEvent event" — o primeiro evento publicado
    # precisa ser o `Task` em si, não um TaskStatusUpdateEvent direto.
    from a2a.types import Task, TaskStatusUpdateEvent

    async def fake_wait(_run_id, **_kw):
        return {"status": "passed", "error": None}

    monkeypatch.setattr(a2a_module, "_wait_for_terminal", fake_wait)

    executor = ArgusAgentExecutor()
    queue = _FakeEventQueue()
    context = _make_context(data={"platform": "web", "app_url": "https://x", "bdd_script": VALID_BDD})

    await executor.execute(context, queue)

    assert isinstance(queue.events[0], Task)
    assert queue.events[0].id == "t1"
    assert isinstance(queue.events[1], TaskStatusUpdateEvent)


async def test_execute_happy_path_emits_submitted_working_completed(configured_provider, monkeypatch):
    from a2a.types import TaskState

    async def fake_wait(_run_id, **_kw):
        return {"status": "passed", "error": None}

    monkeypatch.setattr(a2a_module, "_wait_for_terminal", fake_wait)

    executor = ArgusAgentExecutor()
    queue = _FakeEventQueue()
    context = _make_context(data={"platform": "web", "app_url": "https://x", "bdd_script": VALID_BDD})

    await executor.execute(context, queue)

    assert _status_states(queue) == [
        TaskState.TASK_STATE_SUBMITTED, TaskState.TASK_STATE_WORKING, TaskState.TASK_STATE_COMPLETED,
    ]
    assert executor._task_to_run["t1"]  # run_id registrado pro cancel() achar depois


async def test_execute_failed_run_emits_failed_not_completed(configured_provider, monkeypatch):
    from a2a.types import TaskState

    async def fake_wait(_run_id, **_kw):
        return {"status": "failed", "error": None}

    monkeypatch.setattr(a2a_module, "_wait_for_terminal", fake_wait)

    executor = ArgusAgentExecutor()
    queue = _FakeEventQueue()
    context = _make_context(data={"platform": "web", "app_url": "https://x", "bdd_script": VALID_BDD})

    await executor.execute(context, queue)

    assert _status_states(queue) == [
        TaskState.TASK_STATE_SUBMITTED, TaskState.TASK_STATE_WORKING, TaskState.TASK_STATE_FAILED,
    ]


async def test_execute_validation_error_emits_submitted_then_failed_without_working(configured_provider):
    from a2a.types import TaskState

    executor = ArgusAgentExecutor()
    queue = _FakeEventQueue()
    # android sem binary_url — RunServiceError antes de qualquer run existir.
    context = _make_context(data={"platform": "android", "bdd_script": VALID_BDD})

    await executor.execute(context, queue)

    assert _status_states(queue) == [TaskState.TASK_STATE_SUBMITTED, TaskState.TASK_STATE_FAILED]
    assert "t1" not in executor._task_to_run


async def test_execute_without_configured_provider_fails_gracefully():
    executor = ArgusAgentExecutor()
    queue = _FakeEventQueue()
    context = _make_context(data={"platform": "web", "app_url": "https://x", "bdd_script": VALID_BDD})

    await executor.execute(context, queue)  # não levanta

    from a2a.types import TaskState
    assert _status_states(queue)[-1] == TaskState.TASK_STATE_FAILED


# ─── ArgusAgentExecutor.cancel ───────────────────────────────────────────────


async def test_cancel_requests_cancellation_for_the_mapped_run(configured_provider, monkeypatch):
    async def fake_wait(_run_id, **_kw):
        return {"status": "passed", "error": None}

    monkeypatch.setattr(a2a_module, "_wait_for_terminal", fake_wait)

    executor = ArgusAgentExecutor()
    queue = _FakeEventQueue()
    context = _make_context(data={"platform": "web", "app_url": "https://x", "bdd_script": VALID_BDD})
    await executor.execute(context, queue)
    run_id = executor._task_to_run["t1"]
    # a run já terminou "passed" (fake_wait) — mas o teste só quer provar
    # que cancel() acha o run_id certo e chama request_cancel; o
    # comportamento de "já terminou" é responsabilidade do run_service
    # (testado em test_run_service.py), não repetido aqui.
    store.update_run_status(run_id, "running")  # reabre pra cancel() não estourar RunServiceError

    cancel_queue = _FakeEventQueue()
    await executor.cancel(context, cancel_queue)

    assert store.is_cancel_requested(run_id) is True


async def test_cancel_without_a_mapped_run_does_not_raise():
    executor = ArgusAgentExecutor()
    queue = _FakeEventQueue()
    context = _make_context(task_id="nunca-executado", context_id="c1")
    await executor.cancel(context, queue)  # não levanta, mesmo sem run mapeada


# ─── ponta a ponta via HTTP contra o app real (roteamento + auth) ─────────
# Um roundtrip completo de SendMessage esperaria a run terminar de verdade
# — sem um worker rodando durante os testes, ficaria pendurado até o
# timeout de 600s. Isso é coberto ao vivo (worker real processando),
# ver PLANO.md F6; aqui só prova que o AgentCard resolve e que /a2a fala
# JSON-RPC de verdade (roteamento certo, sem as armadilhas de Mount que o
# MCP teve).


def test_agent_card_resolves_via_http():
    from starlette.testclient import TestClient

    from src.main import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        resp = client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Argus Agent"
        assert body["skills"][0]["id"] == "execute_qa_test"


def test_a2a_jsonrpc_endpoint_speaks_jsonrpc():
    from starlette.testclient import TestClient

    from src.main import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        resp = client.post(
            "/a2a",
            json={"jsonrpc": "2.0", "id": 1, "method": "NotARealMethod", "params": {}},
            headers={"x-a2a-version": "1.0"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32601  # "Method not found" — prova que é JSON-RPC de verdade
