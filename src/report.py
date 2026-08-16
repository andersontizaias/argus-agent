"""Argus Agent — compilação do relatório de uma run: report.json + report.html.

Agrega cenários/passos/evidências (já persistidos no banco por
src/agent/nodes.py durante a execução) num diretório de artefatos por run —
`~/.argus/artifacts/{run_id}/` — e fecha o status final da run. O
`report.html` é um Jinja2 standalone: caminhos de screenshot são relativos,
então o diretório inteiro (ou o zip dele) abre offline sem depender do
servidor do Argus estar de pé."""
import json
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Template

from src import store
from src.settings import artifacts_dir

_HTML_TEMPLATE = Template("""\
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Relatório Argus — {{ run.id }}</title>
<style>
  body { font-family: -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 2rem; }
  h1 { font-size: 1.4rem; }
  .summary { display: flex; flex-wrap: wrap; gap: 1rem 1.5rem; margin-bottom: 1.5rem; }
  .summary div { background: #1e293b; padding: 0.75rem 1.25rem; border-radius: 8px; }
  .scenario { background: #1e293b; border-radius: 10px; padding: 1rem 1.25rem; margin-bottom: 1rem; }
  .scenario h2 { margin: 0 0 0.5rem; font-size: 1.1rem; }
  .status { display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
  .status-passed { background: #14532d; color: #86efac; }
  .status-failed { background: #7f1d1d; color: #fca5a5; }
  .status-skipped { background: #334155; color: #94a3b8; }
  .step { padding: 0.4rem 0 0.4rem 1rem; border-left: 2px solid #334155; margin-left: 0.25rem; }
  .step-error { color: #fca5a5; font-size: 0.85rem; margin-top: 0.25rem; }
  .evidence img { max-width: 320px; border-radius: 6px; margin-top: 0.5rem; border: 1px solid #334155; }
</style>
</head>
<body>
<h1>Relatório Argus — run {{ run.id }}</h1>
<div class="summary">
  <div>Status: <strong>{{ run.status }}</strong></div>
  <div>Cenários: {{ run.scenarios_passed }}/{{ run.scenarios_total }} passaram</div>
  <div>Plataforma: {{ run.platform }}</div>
  <div>Modelo: {{ run.llm_provider }}/{{ run.llm_model }}</div>
  <div>Tokens: {{ run.tokens_in }} in / {{ run.tokens_out }} out</div>
  <div>Custo estimado: ${{ "%.4f"|format(run.cost_usd) }}</div>
</div>
{% if run.mode == "explore" %}
<div class="scenario">
  <h2>Exploração — script Gherkin gerado</h2>
  <p>Sem passo de entrada nesse modo: o agente navegou sozinho e o script \
  abaixo é um CANDIDATO — revise antes de usar como run de regressão.</p>
  {% for ev in exploration_video %}
  <div class="evidence"><video src="{{ ev.path }}" controls style="max-width: 480px; border-radius: 6px;"></video></div>
  {% endfor %}
  <pre style="white-space: pre-wrap; background: #0f172a; padding: 1rem; border-radius: 6px;">{{ run.generated_bdd_script }}</pre>
</div>
{% else %}
{% for scenario in scenarios %}
<div class="scenario">
  <h2>{{ scenario.name }} <span class="status status-{{ scenario.status }}">{{ scenario.status }}</span></h2>
  {% if scenario.failure_reason %}<p class="step-error">{{ scenario.failure_reason }}</p>{% endif %}
  {% for step in scenario.steps %}
  <div class="step">
    <strong>{{ step.keyword }}</strong> {{ step.text }}
    <span class="status status-{{ step.status }}">{{ step.status }}</span>
    {% if step.error %}<div class="step-error">{{ step.error }}</div>{% endif %}
    {% for ev in step.evidences %}
    <div class="evidence"><img src="{{ ev.path }}" alt="{{ ev.label }}"></div>
    {% endfor %}
  </div>
  {% endfor %}
</div>
{% endfor %}
{% endif %}
</body>
</html>
""")


def _duration_ms(started: datetime | None, finished: datetime | None) -> int | None:
    if not started or not finished:
        return None
    return int((finished - started).total_seconds() * 1000)


def compile_report(run_id: str) -> Path:
    run = store.get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} não encontrada.")

    scenarios_rows = store.list_scenarios(run_id)
    evidences_by_step: dict[str, list] = {}
    for ev in store.list_evidences(run_id):
        evidences_by_step.setdefault(ev.step_id or "", []).append(ev)

    run_dir = artifacts_dir() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    scenarios_data = []
    passed_count = 0
    failed_count = 0
    for scenario in scenarios_rows:
        steps_rows = store.list_steps(scenario.id)
        steps_data = []
        for step in steps_rows:
            evidences = [
                {
                    "type": ev.type,
                    "label": ev.label,
                    "path": str(Path(ev.path).relative_to(run_dir)) if _is_within(ev.path, run_dir) else ev.path,
                }
                for ev in evidences_by_step.get(step.id, [])
            ]
            steps_data.append({
                "keyword": step.keyword,
                "text": step.text,
                "status": step.status,
                "error": step.error,
                "attempts": step.attempts,
                "duration_ms": step.duration_ms if step.duration_ms is not None else _duration_ms(step.started_at, step.finished_at),
                "evidences": evidences,
            })
        if scenario.status == "passed":
            passed_count += 1
        elif scenario.status == "failed":
            failed_count += 1
        scenarios_data.append({
            "name": scenario.name,
            "tags": scenario.tags.split(",") if scenario.tags else [],
            "status": scenario.status,
            "failure_reason": scenario.failure_reason,
            "duration_ms": _duration_ms(scenario.started_at, scenario.finished_at),
            "steps": steps_data,
        })

    total = len(scenarios_rows)
    store.set_run_totals(run_id, total=total, passed=passed_count, failed=failed_count)

    # Uma run que já terminou em "error" (parse_bdd/provision_target falhou
    # antes de qualquer cenário rodar de verdade) NUNCA deve ser recalculada
    # pra passed/failed aqui — "error" é sobre o AMBIENTE (script inválido,
    # navegador não subiu), não sobre o resultado dos testes, e um cenário
    # "pending" (nunca chegou a rodar) não pode virar "passou" só porque
    # `failed_count` ficou em zero.
    if run.status == "error":
        final_status = "error"
    elif store.is_cancel_requested(run_id):
        final_status = "canceled"
    else:
        final_status = "passed" if failed_count == 0 else "failed"
    store.update_run_status(run_id, final_status, finished_at=True)
    run = store.get_run(run_id)  # relê com os totais/status atualizados
    if not run:  # pragma: no cover — checado no início da função, não pode sumir no meio
        raise ValueError(f"Run {run_id} não encontrada.")

    # Vídeo da exploração (se houver): evidência de run inteira, sem
    # step_id — cai na mesma chave "" usada acima pros passos sem
    # evidência específica (não é o caso aqui, mas o dict já agrupa por
    # step_id, e vídeo de exploração nunca tem um).
    exploration_video = [
        {"label": ev.label, "path": str(Path(ev.path).relative_to(run_dir)) if _is_within(ev.path, run_dir) else ev.path}
        for ev in evidences_by_step.get("", []) if ev.type == "video"
    ]

    report_data = {
        "run": {
            "id": run.id,
            "status": run.status,
            "mode": run.mode,
            "platform": run.platform,
            "app_url": run.app_url,
            "llm_provider": run.llm_provider,
            "llm_model": run.llm_model,
            "scenarios_total": run.scenarios_total,
            "scenarios_passed": run.scenarios_passed,
            "scenarios_failed": run.scenarios_failed,
            "tokens_in": run.tokens_in,
            "tokens_out": run.tokens_out,
            "cost_usd": run.cost_usd,
            "duration_ms": _duration_ms(run.started_at, run.finished_at),
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "generated_bdd_script": run.generated_bdd_script,
        },
        "scenarios": scenarios_data,
        "exploration_video": exploration_video,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    (run_dir / "report.json").write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
    html = _HTML_TEMPLATE.render(run=report_data["run"], scenarios=scenarios_data, exploration_video=exploration_video)
    (run_dir / "report.html").write_text(html, encoding="utf-8")
    store.set_run_artifacts_dir(run_id, str(run_dir))

    return run_dir / "report.json"


def _is_within(path: str, base: Path) -> bool:
    try:
        Path(path).relative_to(base)
        return True
    except ValueError:
        return False


async def render_report_pdf(run_id: str) -> Path:
    """Renderiza o report.html já compilado pra PDF via Chromium headless
    (Playwright — já é dependência do projeto pra automação web, então não
    precisa de lib nova tipo weasyprint). Abre o arquivo direto do disco por
    `file://` em vez de passar pela API: assim os `<img src="screenshots/
    x.png">` relativos resolvem contra o próprio diretório do HTML igual a
    quando alguém abre o relatório offline, sem depender do servidor do
    Argus estar de pé nem duplicar a lógica de asset da rota catch-all.

    Cacheia em report.pdf ao lado do report.html — só re-renderiza (custo de
    subir um Chromium) se o HTML for mais novo que o PDF já gerado."""
    run = store.get_run(run_id)
    if not run or not run.artifacts_dir:
        raise ValueError(f"Run {run_id} não encontrada.")

    run_dir = Path(run.artifacts_dir)
    html_path = run_dir / "report.html"
    if not html_path.exists():
        raise FileNotFoundError("report.html not found.")

    pdf_path = run_dir / "report.pdf"
    if pdf_path.exists() and pdf_path.stat().st_mtime >= html_path.stat().st_mtime:
        return pdf_path

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(html_path.resolve().as_uri())
            await page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "16mm", "bottom": "16mm", "left": "12mm", "right": "12mm"},
            )
        finally:
            await browser.close()

    return pdf_path
