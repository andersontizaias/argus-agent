import pytest

from src import store, worker

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _reset_shutdown_flag():
    worker._shutdown_requested = False
    yield
    worker._shutdown_requested = False


async def test_process_next_queued_run_returns_false_when_empty(monkeypatch):
    assert await worker._process_next_queued_run() is False


async def test_process_next_queued_run_processes_oldest_first(monkeypatch):
    run1 = store.create_run(platform="web", bdd_script="...")
    store.create_run(platform="web", bdd_script="...")

    processed_ids = []

    async def _fake_run_graph(run_id):
        processed_ids.append(run_id)
        store.update_run_status(run_id, "passed", finished_at=True)

    monkeypatch.setattr(worker, "run_graph", _fake_run_graph)

    processed = await worker._process_next_queued_run()
    assert processed is True
    assert processed_ids == [run1.id]


async def test_process_next_queued_run_marks_error_on_unhandled_exception(monkeypatch):
    run = store.create_run(platform="web", bdd_script="...")

    async def _broken_run_graph(_run_id):
        raise RuntimeError("crash total")

    monkeypatch.setattr(worker, "run_graph", _broken_run_graph)

    processed = await worker._process_next_queued_run()
    assert processed is True
    updated = store.get_run(run.id)
    assert updated.status == "error"
    assert "crash total" in updated.error


async def test_loop_stops_when_shutdown_requested(monkeypatch):
    monkeypatch.setattr(worker, "POLL_INTERVAL_SECONDS", 0)

    call_count = 0

    async def _fake_process():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            worker._shutdown_requested = True
        return False

    monkeypatch.setattr(worker, "_process_next_queued_run", _fake_process)
    await worker._loop()
    assert call_count == 2


def test_request_shutdown_sets_flag():
    assert worker._shutdown_requested is False
    worker._request_shutdown(15, None)
    assert worker._shutdown_requested is True
