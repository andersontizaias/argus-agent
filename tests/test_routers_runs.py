import json

from fastapi.testclient import TestClient

from src import store
from src.main import app

VALID_BDD = "# language: pt\nFuncionalidade: X\n  Cenario: Y\n    Dado algo\n"


def _client():
    return TestClient(app)


def _configure_default_provider():
    with _client() as client:
        client.post("/api/config", json={
            "anthropic_api_key": "sk-ant-abcdefgh12345678",
            "default_llm_provider": "anthropic",
            "default_llm_model": "claude-3-5-haiku-latest",
        })


def test_create_run_requires_valid_platform():
    with _client() as client:
        resp = client.post("/api/runs", json={"platform": "desktop", "bdd_script": VALID_BDD})
    assert resp.status_code == 400
    assert "Invalid platform" in resp.json()["error"]


def test_create_run_rejects_empty_bdd_script():
    with _client() as client:
        resp = client.post("/api/runs", json={"platform": "web", "bdd_script": "   "})
    assert resp.status_code == 400


def test_create_run_rejects_invalid_bdd_syntax():
    with _client() as client:
        resp = client.post("/api/runs", json={"platform": "web", "bdd_script": "isso não é gherkin {{{"})
    assert resp.status_code == 400


def test_create_run_rejects_missing_test_data_placeholder():
    script = "# language: pt\nFuncionalidade: X\n  Cenario: Y\n    Quando preencho <campo>\n"
    with _client() as client:
        resp = client.post("/api/runs", json={"platform": "web", "bdd_script": script})
    assert resp.status_code == 400
    assert "campo" in resp.json()["error"]


def test_create_run_without_any_provider_configured_returns_400():
    with _client() as client:
        resp = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD})
    assert resp.status_code == 400
    assert "provider" in resp.json()["error"].lower()


def test_create_run_uses_configured_default_provider():
    _configure_default_provider()
    with _client() as client:
        resp = client.post("/api/runs", json={"platform": "web", "app_url": "https://example.com", "bdd_script": VALID_BDD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert body["llm_provider"] == "anthropic"
    assert body["llm_model"] == "claude-3-5-haiku-latest"


def test_create_run_explicit_provider_overrides_default():
    _configure_default_provider()
    with _client() as client:
        client.post("/api/config", json={"ollama_base_url": "http://localhost:11434"})
        resp = client.post("/api/runs", json={
            "platform": "web", "bdd_script": VALID_BDD,
            "llm_provider": "ollama", "llm_model": "qwen2.5:14b",
        })
    assert resp.status_code == 200
    assert resp.json()["llm_provider"] == "ollama"


def test_create_run_rejects_unknown_explicit_provider():
    _configure_default_provider()
    with _client() as client:
        resp = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD, "llm_provider": "not-a-provider"})
    assert resp.status_code == 400


def test_get_run_not_found():
    with _client() as client:
        resp = client.get("/api/runs/does-not-exist")
    assert resp.status_code == 404


def test_get_run_detail_includes_scenarios_and_never_leaks_test_data_values():
    _configure_default_provider()
    script = '# language: pt\nFuncionalidade: X\n  Cenario: Y\n    Quando preencho <usuario>\n'
    with _client() as client:
        created = client.post("/api/runs", json={
            "platform": "web", "bdd_script": script, "test_data": {"usuario": "segredo123"},
        }).json()

        # Cenários/passos só são persistidos quando o worker processa a run
        # (nó parse_bdd) — POST /api/runs só valida a sintaxe. Simula esse
        # processamento pra testar a serialização do detalhe com cenários.
        from src.bdd import parse_bdd_script
        store.replace_scenarios(created["id"], parse_bdd_script(script))

        resp = client.get(f"/api/runs/{created['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bdd_script"] == script
    assert body["test_data_keys"] == ["usuario"]
    assert "segredo123" not in json.dumps(body)
    assert len(body["scenarios"]) == 1
    assert body["scenarios"][0]["name"] == "Y"
    assert len(body["scenarios"][0]["steps"]) == 1


def test_list_runs_paginated_and_total():
    _configure_default_provider()
    with _client() as client:
        for _ in range(3):
            client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD})
        resp = client.get("/api/runs?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["runs"]) == 2
    assert body["total"] == 3
    assert body["limit"] == 2


def test_list_runs_filters_by_status_and_platform():
    _configure_default_provider()
    with _client() as client:
        r1 = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD})
        store.update_run_status(r1["id"], "passed", finished_at=True)

        resp = client.get("/api/runs?status=passed")
        assert resp.json()["total"] == 1
        resp = client.get("/api/runs?platform=android")
        assert resp.json()["total"] == 0


def test_list_runs_clamps_limit_to_100():
    _configure_default_provider()
    with _client() as client:
        client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD})
        resp = client.get("/api/runs?limit=9999")
    assert resp.json()["limit"] == 100


def test_cancel_run_sets_flag():
    _configure_default_provider()
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        resp = client.post(f"/api/runs/{created['id']}/cancel")
    assert resp.status_code == 200
    assert resp.json()["cancel_requested"] is True
    assert store.get_run(created["id"]).cancel_requested is True


def test_cancel_run_not_found():
    with _client() as client:
        resp = client.post("/api/runs/does-not-exist/cancel")
    assert resp.status_code == 404


def test_cancel_run_already_terminal_returns_400():
    _configure_default_provider()
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        store.update_run_status(created["id"], "passed", finished_at=True)
        resp = client.post(f"/api/runs/{created['id']}/cancel")
    assert resp.status_code == 400


def test_report_not_ready_returns_404():
    _configure_default_provider()
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        resp = client.get(f"/api/runs/{created['id']}/report")
    assert resp.status_code == 404


def test_report_returns_json_once_available(tmp_path):
    _configure_default_provider()
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        report_data = {"run": {"id": created["id"], "status": "passed"}, "scenarios": []}
        (tmp_path / "report.json").write_text(json.dumps(report_data))
        store.set_run_artifacts_dir(created["id"], str(tmp_path))

        resp = client.get(f"/api/runs/{created['id']}/report")
    assert resp.status_code == 200
    assert resp.json() == report_data


def test_report_html_returns_file_once_available(tmp_path):
    _configure_default_provider()
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        (tmp_path / "report.html").write_text("<html>relatorio</html>")
        store.set_run_artifacts_dir(created["id"], str(tmp_path))

        resp = client.get(f"/api/runs/{created['id']}/report.html")
    assert resp.status_code == 200
    assert "relatorio" in resp.text


def test_report_html_not_ready_returns_404():
    _configure_default_provider()
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        resp = client.get(f"/api/runs/{created['id']}/report.html")
    assert resp.status_code == 404


def test_artifacts_zip_contains_files(tmp_path):
    _configure_default_provider()
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "report.json").write_text("{}")
    (tmp_path / "screenshots" / "0_0_ok.png").write_bytes(b"fake-png-bytes")

    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        store.set_run_artifacts_dir(created["id"], str(tmp_path))
        resp = client.get(f"/api/runs/{created['id']}/artifacts.zip")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
    assert "report.json" in names
    assert "screenshots/0_0_ok.png" in names


def test_artifacts_zip_not_ready_returns_404():
    _configure_default_provider()
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        resp = client.get(f"/api/runs/{created['id']}/artifacts.zip")
    assert resp.status_code == 404


def test_get_evidence_returns_file(tmp_path):
    _configure_default_provider()
    png_path = tmp_path / "shot.png"
    png_path.write_bytes(b"fake-png-bytes")
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()

    evidence = store.add_evidence(created["id"], None, "screenshot", "ok", str(png_path))
    with _client() as client:
        resp = client.get(f"/api/evidences/{evidence.id}")
    assert resp.status_code == 200
    assert resp.content == b"fake-png-bytes"


def test_get_evidence_not_found():
    with _client() as client:
        resp = client.get("/api/evidences/does-not-exist")
    assert resp.status_code == 404


def test_get_evidence_missing_file_on_disk_returns_404():
    _configure_default_provider()
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
    evidence = store.add_evidence(created["id"], None, "screenshot", "ok", "/tmp/does-not-exist-argus.png")
    with _client() as client:
        resp = client.get(f"/api/evidences/{evidence.id}")
    assert resp.status_code == 404


def test_report_asset_serves_relative_path_used_by_report_html(tmp_path):
    # report.html embute <img src="screenshots/x.png"> (caminho relativo à
    # própria URL do relatório) — sem esta rota, abrir o relatório pela API
    # (em vez do arquivo no disco) quebra essas imagens (achado ao vivo).
    _configure_default_provider()
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "0_0_ok.png").write_bytes(b"fake-png-bytes")
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        store.set_run_artifacts_dir(created["id"], str(tmp_path))
        resp = client.get(f"/api/runs/{created['id']}/screenshots/0_0_ok.png")
    assert resp.status_code == 200
    assert resp.content == b"fake-png-bytes"


def test_report_asset_rejects_path_traversal(tmp_path):
    # "%2e%2e" (não "..") de propósito — um ".." literal na URL é
    # normalizado pelo próprio cliente HTTP (curl, browsers, httpx) antes
    # até de sair, então nunca chegaria no handler pra testar a checagem de
    # verdade; codificado, sobrevive ao parsing e só vira ".." depois do
    # decode da própria rota — foi assim que essa checagem foi validada ao
    # vivo (achado ao vivo).
    _configure_default_provider()
    secret = tmp_path.parent / "argus-report-asset-traversal-secret.txt"
    secret.write_text("segredo")
    try:
        with _client() as client:
            created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
            store.set_run_artifacts_dir(created["id"], str(tmp_path))
            resp = client.get(
                f"/api/runs/{created['id']}/%2e%2e/{secret.name}"
            )
        assert resp.status_code == 404
        assert resp.json() == {"error": "File not found."}
    finally:
        secret.unlink(missing_ok=True)


def test_report_asset_missing_file_returns_404(tmp_path):
    _configure_default_provider()
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        store.set_run_artifacts_dir(created["id"], str(tmp_path))
        resp = client.get(f"/api/runs/{created['id']}/screenshots/does-not-exist.png")
    assert resp.status_code == 404


def test_report_asset_does_not_shadow_specific_routes(tmp_path):
    # Regressão: a rota catch-all precisa vir DEPOIS de cancel/stream/report/
    # report.html/artifacts.zip no arquivo — senão ela rouba essas URLs.
    _configure_default_provider()
    (tmp_path / "report.json").write_text('{"run": {}, "scenarios": []}')
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        store.set_run_artifacts_dir(created["id"], str(tmp_path))
        resp = client.get(f"/api/runs/{created['id']}/report")
    assert resp.status_code == 200
    assert resp.json() == {"run": {}, "scenarios": []}


def test_stream_run_emits_initial_snapshot_and_closes_when_terminal():
    _configure_default_provider()
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        store.update_run_status(created["id"], "passed", finished_at=True)

        with client.stream("GET", f"/api/runs/{created['id']}/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = "".join(resp.iter_text())
    assert "event: run_snapshot" in body
    assert '"status": "passed"' in body


def test_stream_run_not_found():
    with _client() as client:
        resp = client.get("/api/runs/does-not-exist/stream")
    assert resp.status_code == 404


def test_stream_run_replays_events_after_seq():
    from src.events import publish_event

    _configure_default_provider()
    with _client() as client:
        created = client.post("/api/runs", json={"platform": "web", "bdd_script": VALID_BDD}).json()
        publish_event(created["id"], "scenario_running", {"name": "Y"})
        store.update_run_status(created["id"], "passed", finished_at=True)

        with client.stream("GET", f"/api/runs/{created['id']}/stream?after=0") as resp:
            body = "".join(resp.iter_text())
    assert "event: scenario_running" in body
