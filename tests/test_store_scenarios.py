from src import store
from src.bdd import ParsedScenario, ParsedStep


def _make_run():
    return store.create_run(platform="web", bdd_script="...", app_url="https://example.com")


def _sample_scenarios():
    return [
        ParsedScenario(name="Cenário A", steps=[ParsedStep("Given", "passo 1"), ParsedStep("When", "passo 2")]),
        ParsedScenario(name="Cenário B", steps=[ParsedStep("Given", "passo 1")], tags=["smoke"]),
    ]


def test_replace_scenarios_persists_scenarios_and_steps():
    run = _make_run()
    store.replace_scenarios(run.id, _sample_scenarios())

    scenarios = store.list_scenarios(run.id)
    assert [s.name for s in scenarios] == ["Cenário A", "Cenário B"]
    assert scenarios[0].status == "pending"
    assert scenarios[1].tags == "smoke"

    steps_a = store.list_steps(scenarios[0].id)
    assert [s.text for s in steps_a] == ["passo 1", "passo 2"]
    assert [s.keyword for s in steps_a] == ["Given", "When"]


def test_replace_scenarios_is_idempotent():
    run = _make_run()
    store.replace_scenarios(run.id, _sample_scenarios())
    store.replace_scenarios(run.id, _sample_scenarios()[:1])
    assert len(store.list_scenarios(run.id)) == 1


def test_get_scenario_roundtrip():
    run = _make_run()
    store.replace_scenarios(run.id, _sample_scenarios())
    scenario = store.list_scenarios(run.id)[0]
    fetched = store.get_scenario(scenario.id)
    assert fetched is not None
    assert fetched.name == scenario.name


def test_get_scenario_missing_returns_none():
    assert store.get_scenario("does-not-exist") is None


def test_update_scenario_status_sets_fields():
    run = _make_run()
    store.replace_scenarios(run.id, _sample_scenarios())
    scenario = store.list_scenarios(run.id)[0]

    store.update_scenario_status(scenario.id, "running", started_at=True)
    updated = store.get_scenario(scenario.id)
    assert updated.status == "running"
    assert updated.started_at is not None

    store.update_scenario_status(scenario.id, "failed", finished_at=True, failure_reason="deu ruim")
    updated = store.get_scenario(scenario.id)
    assert updated.status == "failed"
    assert updated.failure_reason == "deu ruim"
    assert updated.finished_at is not None


def test_update_scenario_status_missing_scenario_is_noop():
    store.update_scenario_status("does-not-exist", "running")  # não deve levantar


def test_update_step_status_sets_fields():
    run = _make_run()
    store.replace_scenarios(run.id, _sample_scenarios())
    step = store.list_steps(store.list_scenarios(run.id)[0].id)[0]

    store.update_step_status(step.id, "failed", error="timeout", attempts=2, duration_ms=1500, finished_at=True)
    steps = store.list_steps(step.scenario_id)
    updated = next(s for s in steps if s.id == step.id)
    assert updated.status == "failed"
    assert updated.error == "timeout"
    assert updated.attempts == 2
    assert updated.duration_ms == 1500
    assert updated.finished_at is not None


def test_update_step_status_missing_step_is_noop():
    store.update_step_status("does-not-exist", "passed")  # não deve levantar


def test_create_run_encrypts_test_data():
    run = store.create_run(platform="web", bdd_script="...", test_data={"usuario": "standard_user"})
    assert run.test_data_enc != ""
    assert "standard_user" not in run.test_data_enc
    assert store.get_run_test_data(run.id) == {"usuario": "standard_user"}


def test_get_run_test_data_empty_when_no_data():
    run = store.create_run(platform="web", bdd_script="...")
    assert store.get_run_test_data(run.id) == {}


def test_get_run_test_data_missing_run_returns_empty():
    assert store.get_run_test_data("does-not-exist") == {}


def test_update_run_status_and_totals():
    run = _make_run()
    store.update_run_status(run.id, "running", started_at=True)
    store.set_run_totals(run.id, total=2, passed=1, failed=1)
    updated = store.get_run(run.id)
    assert updated.status == "running"
    assert updated.scenarios_total == 2
    assert updated.scenarios_passed == 1
    assert updated.scenarios_failed == 1
    assert updated.started_at is not None


def test_update_run_status_missing_run_is_noop():
    store.update_run_status("does-not-exist", "error", error="x")  # não deve levantar


def test_cancel_flow():
    run = _make_run()
    assert store.is_cancel_requested(run.id) is False
    store.request_cancel(run.id)
    assert store.is_cancel_requested(run.id) is True


def test_list_queued_run_ids_orders_by_creation():
    run1 = _make_run()
    run2 = _make_run()
    queued = store.list_queued_run_ids()
    assert queued.index(run1.id) < queued.index(run2.id)


def test_list_runs_orders_newest_first():
    _make_run()
    run2 = _make_run()
    runs = store.list_runs(limit=1)
    assert runs[0].id == run2.id


def test_set_run_artifacts_dir():
    run = _make_run()
    store.set_run_artifacts_dir(run.id, "/tmp/argus/x")
    assert store.get_run(run.id).artifacts_dir == "/tmp/argus/x"


def test_set_run_job_id():
    run = _make_run()
    store.set_run_job_id(run.id, "job-123")
    assert store.get_run(run.id).job_id == "job-123"
