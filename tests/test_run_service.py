"""Testes de src/run_service.py — casos de uso compartilhados entre REST e
MCP. As mensagens/status HTTP exatos de cada validação já são cobertos via
tests/test_routers_runs.py (que exercita esse mesmo código através do
router); aqui o foco é o contrato do serviço em si (tipos de exceção,
formato dos dicts) e os caminhos que só o MCP usa (get_report_dict,
request_cancel sem passar pelo router)."""
import json

import pytest

from src import run_service, store
from src.llm_providers import SUPPORTED_PROVIDERS, default_model_setting_name
from src.user_secrets import set_secret_plain

VALID_BDD = "# language: pt\nFuncionalidade: X\n  Cenario: Y\n    Dado algo\n"


@pytest.fixture
def configured_provider():
    provider = SUPPORTED_PROVIDERS[0]
    set_secret_plain(provider.secret_name, "sk-fake-key-not-used")
    store.set_setting("default_llm_provider", provider.id)
    store.set_setting(default_model_setting_name(provider), provider.example_model)
    return provider


def test_create_run_web_happy_path(configured_provider):
    run = run_service.create_run(platform="web", bdd_script=VALID_BDD, app_url="https://example.com")
    assert run.platform == "web"
    assert run.status == "queued"


def test_create_run_explore_happy_path(configured_provider):
    run = run_service.create_run(
        platform="web", app_url="https://example.com", mode="explore", confirmed_non_production=True,
    )
    assert run.mode == "explore"
    assert run.bdd_script == ""
    assert run.max_actions == run_service.DEFAULT_EXPLORE_MAX_ACTIONS
    assert run.confirmed_non_production is True


def test_create_run_explore_requires_confirmed_non_production(configured_provider):
    with pytest.raises(run_service.RunServiceError, match="confirmed_non_production"):
        run_service.create_run(platform="web", app_url="https://example.com", mode="explore")


def test_create_run_explore_does_not_require_bdd_script(configured_provider):
    # Diferente do modo execute — sem script de entrada nesse modo, o
    # agente explora sozinho e PRODUZ um (ver src/agent/nodes.py:explore_app).
    run = run_service.create_run(
        platform="web", app_url="https://example.com", bdd_script="", mode="explore",
        confirmed_non_production=True,
    )
    assert run.status == "queued"


def test_create_run_explore_accepts_custom_max_actions(configured_provider):
    run = run_service.create_run(
        platform="web", app_url="https://example.com", mode="explore",
        confirmed_non_production=True, max_actions=10,
    )
    assert run.max_actions == 10


@pytest.mark.parametrize("max_actions", [0, -1, 101])
def test_create_run_explore_rejects_max_actions_out_of_range(configured_provider, max_actions):
    with pytest.raises(run_service.RunServiceError, match="max_actions"):
        run_service.create_run(
            platform="web", app_url="https://example.com", mode="explore",
            confirmed_non_production=True, max_actions=max_actions,
        )


def test_create_run_rejects_invalid_mode(configured_provider):
    with pytest.raises(run_service.RunServiceError, match="Invalid mode"):
        run_service.create_run(platform="web", bdd_script=VALID_BDD, mode="bogus")


def test_create_run_android_requires_binary_url(configured_provider):
    with pytest.raises(run_service.RunServiceError, match="requires binary_url"):
        run_service.create_run(platform="android", bdd_script=VALID_BDD)


def test_create_run_android_happy_path_with_binary_url(configured_provider):
    run = run_service.create_run(platform="android", bdd_script=VALID_BDD, binary_url="https://x/app.apk")
    assert run.platform == "android"
    assert run.binary_url == "https://x/app.apk"


def test_create_run_rejects_invalid_platform(configured_provider):
    with pytest.raises(run_service.RunServiceError, match="Invalid platform"):
        run_service.create_run(platform="desktop", bdd_script=VALID_BDD)


def test_create_run_rejects_empty_bdd_script(configured_provider):
    with pytest.raises(run_service.RunServiceError, match="Empty BDD script"):
        run_service.create_run(platform="web", bdd_script="   ")


def test_create_run_rejects_invalid_bdd_syntax(configured_provider):
    with pytest.raises(run_service.RunServiceError):
        run_service.create_run(platform="web", bdd_script="isso não é gherkin {{{")


def test_create_run_rejects_missing_test_data_placeholder(configured_provider):
    script = "# language: pt\nFuncionalidade: X\n  Cenario: Y\n    Dado preencho <campo>\n"
    with pytest.raises(run_service.RunServiceError, match="campo"):
        run_service.create_run(platform="web", bdd_script=script)


def test_create_run_without_configured_provider_raises():
    # Sem a fixture configured_provider — nenhum default setado.
    with pytest.raises(run_service.RunServiceError, match="No LLM provider configured"):
        run_service.create_run(platform="web", bdd_script=VALID_BDD)


def test_create_run_rejects_unknown_explicit_provider():
    with pytest.raises(run_service.RunServiceError, match="No LLM provider configured"):
        run_service.create_run(platform="web", bdd_script=VALID_BDD, llm_provider="not-a-provider")


def test_request_cancel_raises_not_found_for_unknown_run():
    with pytest.raises(run_service.RunNotFoundError):
        run_service.request_cancel("nao-existe")


def test_request_cancel_raises_when_already_terminal(configured_provider):
    run = run_service.create_run(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    store.update_run_status(run.id, "passed", finished_at=True)
    with pytest.raises(run_service.RunServiceError, match="already finished"):
        run_service.request_cancel(run.id)


def test_request_cancel_happy_path(configured_provider):
    run = run_service.create_run(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    run_service.request_cancel(run.id)
    assert store.is_cancel_requested(run.id) is True


def test_get_run_summary_raises_not_found():
    with pytest.raises(run_service.RunNotFoundError):
        run_service.get_run_summary("nao-existe")


def test_get_run_summary_returns_expected_shape(configured_provider):
    run = run_service.create_run(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    summary = run_service.get_run_summary(run.id)
    assert summary["id"] == run.id
    assert summary["status"] == "queued"
    assert set(summary.keys()) >= {
        "id", "platform", "status", "llm_provider", "llm_model",
        "scenarios_total", "scenarios_passed", "scenarios_failed", "created_at",
    }


def test_get_report_dict_raises_not_found():
    with pytest.raises(run_service.RunNotFoundError):
        run_service.get_report_dict("nao-existe")


def test_get_report_dict_raises_when_run_has_no_artifacts_dir(configured_provider):
    run = run_service.create_run(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    with pytest.raises(run_service.RunServiceError, match="not available yet"):
        run_service.get_report_dict(run.id)


def test_get_report_dict_raises_when_report_json_missing(configured_provider, tmp_path):
    run = run_service.create_run(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    store.set_run_artifacts_dir(run.id, str(tmp_path))
    with pytest.raises(run_service.RunServiceError, match="report.json not found"):
        run_service.get_report_dict(run.id)


def test_get_report_dict_returns_parsed_json(configured_provider, tmp_path):
    run = run_service.create_run(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    store.set_run_artifacts_dir(run.id, str(tmp_path))
    (tmp_path / "report.json").write_text(json.dumps({"run": {"id": run.id}, "scenarios": []}), encoding="utf-8")
    report = run_service.get_report_dict(run.id)
    assert report["run"]["id"] == run.id


def test_list_run_summaries_clamps_limit(configured_provider):
    result = run_service.list_run_summaries(limit=500)
    assert result["limit"] == 100


def test_list_run_summaries_returns_created_runs(configured_provider):
    run_service.create_run(platform="web", bdd_script=VALID_BDD, app_url="https://x")
    result = run_service.list_run_summaries(limit=10)
    assert result["total"] >= 1
    assert any(r["platform"] == "web" for r in result["runs"])
