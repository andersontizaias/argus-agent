# Plano — Argus Agent (QA autônomo multi-stack)

## Contexto

Criar do zero, em `/Users/little/Documents/Projects/Agents/argus-agent` (diretório vazio), o **Argus Agent**: um agente de QA autônomo com persona de "QA sênior extremamente eficiente". Instalado nativamente numa máquina macOS, ele recebe uma aplicação-alvo (URL web ou binário mobile), um **script BDD (Gherkin)** e a **massa de testes**, e executa os cenários dirigindo a aplicação de verdade — browser via Playwright, Android/iOS via emulador/simulador + Appium — produzindo relatório por cenário com evidências (screenshots, logs). Terá UI web simples (config de provider LLM + criação/acompanhamento de execuções) e três superfícies de integração para CI/CD e fluxos agênticos: **API REST, MCP e A2A**.

## Decisões fechadas com o usuário

- **Motor**: LangGraph (multi-provider via `init_chat_model`)
- **Escopo do MVP**: web + Android + iOS ("tudo de uma vez", entregue em fases verificáveis)
- **Stack**: Python/FastAPI + React (padrões do phalanx-agents reaproveitados)
- **Mobile**: Appium (UiAutomator2 no Android, XCUITest no iOS)
- **Instalação**: nativa no host macOS (sem Docker no caminho crítico — simulador iOS não roda em container)
- **Integração**: REST + MCP + A2A, as três
- **Repositório**: GitHub, criado na fundação via `gh repo create` privado (`andersontizaias/argus-agent`); tornado **público** (licença MIT) na fase de polish, pra eliminar a exigência de token nas instalações (Homebrew/tarball/wizard) e permitir reconhecimento/reuso do código
- **Distribuição**: GitHub Releases com **tarball + install.sh**; **tap Homebrew** entra na fase de polish
- **Design system**: paleta extraída do logo `argus-agent-logo.png` (fornecido pelo usuário) vira tokens do Tailwind — cores primárias/acento da UI derivadas do logo, que também entra como favicon/navbar

## Decisões técnicas (tomadas no planejamento, com justificativa)

| Item | Decisão | Por quê |
|---|---|---|
| Banco | **SQLite (WAL) + SQLAlchemy + Alembic** | Single-machine sem serviço externo; 1-2 runs simultâneas; `db.py`/Alembic do phalanx quase intactos |
| Fila/eventos | **Sem Redis/RQ.** Worker separado (`argus-worker`) faz claim de runs `queued` no SQLite; SSE lê tabela `run_events` (polling 0,5s + heartbeat 15s, replay por `seq`) | Menos dependência no bootstrap; tabela dá replay que o pub/sub do phalanx não dá; worker separado porque LangGraph+Playwright/Appium é pesado |
| Auth | Bind `127.0.0.1` por padrão, UI sem login; API aceita `X-API-Key` (`argus_<prefix>_<random>`, hash argon2, exibida 1x) — item de primeira classe para CI/CD | Ferramenta interna single-machine; o que CI/CD precisa é token de máquina (phalanx não tem) |
| Tools browser | **Playwright direto** com snapshot de acessibilidade + refs numeradas (`[e12] button "Entrar"`), ações por ref | Melhor taxa de acerto de tool-calling, barato em tokens (texto, não imagem), sem dependência de browser-use/MCP externo |
| Checkpointing | `SqliteSaver` (`langgraph-checkpoint-sqlite`), `thread_id = run_id` | Retomada de run após crash do worker |

## Arquitetura

```
  Browser (UI) ──▶ ┌──────────── FastAPI (porta 8765) ────────────┐
  CI/CD (curl) ──▶ │ /        → frontend/dist (estático)          │
  Claude/MCP  ──▶  │ /api/*   → REST (X-API-Key)                  │
  Outro agente ──▶ │ /mcp     → MCP Streamable HTTP               │
                   │ /a2a + /.well-known/agent-card.json → A2A    │
                   └──────────────┬───────────────────────────────┘
                                  │ SQLite WAL (~/.argus/argus.db)
                   ┌──────────────▼───────────────────────────────┐
                   │ argus-worker: claim run queued → grafo       │
                   │ LangGraph → publica progresso em run_events  │
                   └──┬───────────┬──────────────┬────────────────┘
                      │Playwright │Appium :4723  │subprocess
                      ▼           ▼              ▼
                   Chromium    emulador AVD   simulador iOS
                   Artefatos: ~/.argus/artifacts/{run_id}/
```

MCP e A2A são fachadas finas sobre o mesmo `store`/serviço de runs — zero lógica duplicada. Appium sobe on-demand pelo worker (porta dedicada por run mobile).

## Árvore de diretórios

```
argus-agent/
├── pyproject.toml            # uv; scripts: argus, argus-worker, argus-doctor
├── alembic.ini  migrations/  .env.example
├── scripts/
│   ├── bootstrap.sh          # setup nativo idempotente
│   ├── dev.sh                # api + worker + vite
│   └── launchd/              # plists (fase F7)
├── src/
│   ├── main.py               # FastAPI + estático + mount /mcp (+/a2a)
│   ├── db.py  models.py  crypto.py  settings.py
│   ├── llm_providers.py      # lista declarativa + init_chat_model + test_provider
│   ├── worker.py  events.py  auth.py
│   ├── bdd.py                # gherkin-official → plano estruturado
│   ├── report.py             # report.json + report.html (Jinja2) + zip
│   ├── routers/              # runs.py  config.py  api_keys.py  health.py
│   ├── store/                # façade __init__ (padrão phalanx): runs, scenarios, events, config, api_keys
│   ├── agent/                # graph.py  state.py  nodes.py  executor.py  prompts.py (persona pt-BR)
│   ├── tools/                # web.py  mobile.py  device_android.py  device_ios.py
│   │                         # appium_server.py  binary_fetch.py
│   ├── mcp_server.py  a2a_server.py
├── frontend/                 # Vite + React 19 + TS + Tailwind v4 (toolchain do phalanx)
│   └── src/  components/ui/  lib/(api,queries,useRunStream,i18n)  locales/  pages/
├── tests/                    # pytest, coverage ≥90
└── .github/workflows/ci.yml  # lint, mypy, pytest, xenon, jscpd, pip-audit, gitleaks, vitest
```

## O grafo LangGraph

**Parse do BDD é determinístico** (`gherkin-official`, expande Scenario Outline/Background) — o LLM só entra na execução de cada passo contra a tela real. Corta tokens e elimina alucinação estrutural.

Nós: `parse_bdd` → `bind_test_data` (valida placeholders da massa) → `provision_target` (por plataforma: launch Chromium | boot AVD + fetch/install APK + Appium/UiAutomator2 | simctl boot + fetch/install .app + Appium/XCUITest; timeouts generosos; falha aqui = status `error`, não `failed`) → loop `run_scenario` → subgrafo executor por passo → `teardown_target` (emulador fica de pé p/ reuso) → `compile_report`.

**Subgrafo executor (ReAct por passo)**: `prepare_step` (prompt = passo Gherkin + massa relevante + resumo curto dos passos anteriores + snapshot atual; **contexto zerado a cada passo**) → `agent_step` (LLM + tools, máx. 8 iterações; passos `Then` exigem veredito justificado via snapshot) → `finish_step` (screenshot de evidência + grava status + `run_events`). Falha: retry 1x com re-snapshot; persiste → passo `failed`, cenário `failed`, restantes `skipped`, segue pro próximo cenário (semântica Cucumber). Cancelamento via flag checada entre passos. Retomada: worker reencontra run `running` órfã e re-invoca com mesmo `thread_id` (provision idempotente).

## Tools do agente

**Web (Playwright)**: `browser_navigate`, `browser_snapshot` (refs numeradas — a tool central), `browser_click/fill/select(ref)`, `browser_press_key`, `browser_hover`, `browser_scroll`, `browser_wait_for`, `browser_screenshot(label)`, `browser_back`, `browser_get_url`.

**Mobile (Appium)**: `mobile_snapshot` (page source XML filtrado, só visíveis/interativos, com refs), `mobile_tap/type/long_press(ref)`, `mobile_swipe`, `mobile_scroll_to`, `mobile_press_back`, `mobile_hide_keyboard`, `mobile_wait_for`, `mobile_screenshot`, `mobile_launch_app`, `mobile_terminate_app`.

**Gestão de dispositivo (NÃO exposta ao LLM — nós determinísticos)**: `ensure_avd/boot_emulator/adb_install`, `simctl_boot/install`, `fetch_binary(url, auth_secret_ref)` — auth via secret, nunca em claro; valida `.app` de simulador via Info.plist/arquitetura e falha com mensagem clara se receber ipa de device.

## Modelo de dados (SQLite)

- `runs`: platform, app_url, binary_url, binary_auth_secret (nome, não valor), bdd_script, `test_data_enc` (massa cifrada Fernet — contém credenciais), llm_provider/model, status (`queued|provisioning|running|passed|failed|error|canceled`), cancel_requested, totais de cenários, tokens/custo, artifacts_dir, timestamps
- `scenarios`: run_id, position, name, tags, status (`pending|running|passed|failed|skipped`), failure_reason, timestamps
- `steps`: scenario_id, position, keyword, text, status, error, attempts, duration_ms
- `evidences`: run_id, step_id?, type (`screenshot|log|page_source`), label, path
- `run_events`: id autoincrement (= seq p/ SSE replay), run_id, type, payload JSON
- `secrets`: name pk, value_enc (Fernet, master key `ARGUS_SECRET_KEY` em env) — chaves LLM + auth de binários
- `settings`: key/value (provider default, avd name, ios device, max_concurrent_runs, retenção)
- `api_keys`: name, prefix (indexed), key_hash (argon2), last_used_at, revoked

## API REST

`POST /api/runs` · `GET /api/runs` (paginada, filtros) · `GET /api/runs/{id}` · `POST /api/runs/{id}/cancel` · `GET /api/runs/{id}/stream` (SSE, `?after=seq`) · `GET /api/runs/{id}/report` (.json) · `/report.html` · `/artifacts.zip` · `GET /api/evidences/{id}` · `GET/POST /api/config` (masking `****` + preservação, padrão phalanx) · `POST /api/config/test-provider` · CRUD `/api/api-keys` · `GET /api/health` (doctor: db, playwright, adb, simctl, appium, disco).

Fluxo CI/CD: `POST /api/runs` → poll/SSE → exit code do job por `status` → baixa `report.json`.

## MCP e A2A

- **MCP**: FastMCP (SDK oficial `mcp`), Streamable HTTP montado em `/mcp` no mesmo app. Tools: `run_test` (com `wait` opcional), `get_run_status`, `get_report`, `list_runs`, `cancel_run` — fachadas sobre o store.
- **A2A**: `a2a-sdk` oficial, rota `/a2a` + AgentCard em `/.well-known/agent-card.json` (skill `execute_qa_test`, streaming de status mapeando `run_events`). Fase final.

## UI (pt-BR default, i18n)

Identidade visual (extraída de `argus-agent-logo.png`, já no repo — mover para `frontend/public/`):
- **Navy profundo** `#16233B` / `#1B2A4A` (escudo e wordmark "Argus") → cor primária: navbar, botões primários, headings
- **Ciano elétrico** `#0AA6E0` / `#19B5F1` (circuitos e íris) → acento: links, focus rings, status "running", destaques
- **Azul aço** `#2E7DB2` ("Agent") → secundária: badges, texto de apoio
- **Prata/cinza claro** `#C8D2DC` (contorno do olho) → bordas, divisores
- Tokens Tailwind v4 via `@theme` em `frontend/src/index.css` (`--color-argus-primary`, `--color-argus-accent`, `--color-argus-steel`, escala de superfícies claro/escuro derivada do navy); verde/vermelho de status (passed/failed) fora da paleta do logo, escolhidos com contraste AA sobre as superfícies
- Logo completo no login/empty states; só o escudo como favicon e ícone do navbar

- **Config**: cards por provider (lista declarativa copiada do ConfigPage do phalanx) + "Testar provider", provider/modelo default, secrets de fontes de binário, API keys (exibida 1x), badges do `/api/health` (Playwright ✓, Android ✓, iOS ✗…)
- **Nova Execução**: seletor de plataforma → campos condicionais (URL | binário+secret), textarea BDD com validação de sintaxe, editor JSON da massa, seletor provider/modelo
- **Lista de Runs**: tabela paginada, filtros, badges (`3/5 cenários`)
- **Detalhe da Run**: stream ao vivo (hook `useRunStream` adaptado p/ replay por seq): cenários/passos mudando de estado, último screenshot, log de eventos; relatório final embutido com galeria + downloads; botão Cancelar

## Relatório

`~/.argus/artifacts/{run_id}/` com `report.json`, `report.html` (Jinja2 standalone, abre offline), `screenshots/`, `logs/agent.log` (massa de testes **redigida** — valores viram `***`). Retenção configurável (30d default) com prune no worker.

## Repositório GitHub + CI/CD de releases

**Repo**: criado na F0 com `gh repo create andersontizaias/argus-agent --private`, push da fundação já com CI ativa.

**CI (`ci.yml`) — gates de qualidade equivalentes aos do Phalanx, sem exceção:**
- Backend: `ruff check src tests` + `mypy src` + `pytest --cov` com `fail_under = 90`
- Complexidade: `uvx xenon --max-absolute D --max-modules B --max-average B src`
- Duplicação: `npx jscpd@5 src frontend/src --threshold 10`
- Segurança: `uvx pip-audit`, `npm audit`, gitleaks, SBOM (anchore)
- Frontend: `npm ci` + eslint + `tsc -b && vite build` + vitest com coverage
- `ARGUS_SECRET_KEY` efêmera gerada por run de CI (padrão phalanx)
- Diferenças vs phalanx: sem serviços Postgres/Redis (SQLite em arquivo temp) e sem docker build

**Release (`release.yml`) — publicação de versões para instalar nos clients:**
- Dispara em tag `v*` (semver; versão fonte única no `pyproject.toml`, exposta em `/api/health` e no rodapé da UI)
- Roda a CI completa, builda o frontend e empacota `argus-agent-vX.Y.Z.tar.gz` (src, frontend/dist, migrations, scripts, pyproject.toml, uv.lock — sem node_modules/testes)
- Cria GitHub Release com o tarball + `install.sh` anexados e changelog gerado das mensagens de commit
- `scripts/install.sh` (client): pede/recebe `GITHUB_TOKEN` read-only (repo privado), baixa a release mais recente via API, extrai para `~/argus` e roda `bootstrap.sh`; re-executar o script atualiza para a última versão (preserva `~/.argus/` — banco, artefatos e `.env`)
- Fase F7: tap Homebrew (`andersontizaias/homebrew-argus`) com fórmula apontando pro tarball da release; tarball+install.sh continuam como caminho alternativo. Repositórios tornados públicos (MIT) ainda na F7, eliminando a exigência de token

## Bootstrap nativo (`scripts/bootstrap.sh`, idempotente)

1. Homebrew, `uv`, `node@22`, `openjdk@17`
2. Android: `android-commandlinetools` + sdkmanager (platform-tools, emulator, android-35, system-image arm64) + `avdmanager create avd -n argus-android` + `ANDROID_HOME`
3. iOS: checa Xcode/`simctl list runtimes`; se faltar runtime, **instrui** `xcodebuild -downloadPlatform iOS` (não baixa GB sem confirmar)
4. Appium global + drivers uiautomator2/xcuitest (pinados) + `appium driver doctor`
5. `uv sync` + `playwright install chromium` + gera `ARGUS_SECRET_KEY` no `.env` (sem imprimir) + `alembic upgrade head`
6. `npm ci && npm run build`
7. `argus-doctor` final

## Arquivos do phalanx a copiar/adaptar

- `phalanx-agents/src/db.py` → SQLite WAL, busy_timeout, foreign_keys ON
- `phalanx-agents/src/crypto.py` → env `ARGUS_SECRET_KEY`
- `phalanx-agents/src/routers/config.py` → masking/preservação + test-provider
- `phalanx-agents/frontend/src/pages/ConfigPage.tsx` → `LLM_PROVIDERS` declarativo
- `phalanx-agents/frontend/src/lib/useRunStream.ts` → SSE com replay por seq
- `phalanx-agents/frontend/src/components/ui/` + toolchain Vite/Tailwind/vitest
- `phalanx-agents/.github/workflows/ci.yml` → sem Postgres/Redis/docker

## Fases (cada uma com verificação ponta a ponta)

| Fase | Entrega | Verificação |
|---|---|---|
| **F0 Fundação** | scaffold, git init + repo GitHub privado, db/models/Alembic, crypto, store façade, routers config/health, UI shell + Config com paleta do logo, CI com gates do phalanx | `bootstrap.sh` limpo; CI verde ≥90 com xenon/jscpd/pip-audit/gitleaks passando; chave salva na UI volta `sk-a****`; "Testar provider" ok |
| **F1 Agente web** | bdd.py, tools Playwright, grafo + executor + checkpoint, worker, report.json | Run contra site demo (saucedemo.com) com 1 cenário que passa + 1 que falha de propósito → report correto + screenshots |
| **F2 REST + UI runs** | routers runs (SSE, cancel, report, artifacts), API keys, páginas Nova/Lista/Detalhe ao vivo, report.html, `release.yml` + `install.sh` (primeira tag `v0.1.0`) | Run pela UI acompanhada ao vivo; `curl -H X-API-Key` cria/acompanha/baixa; cancelar no meio funciona; release v0.1.0 publicada e instalável via install.sh |
| **F3 Android** | device_android, binary_fetch, appium_server, tools mobile, branch android do provision | Run com APK demo (Sauce Labs My Demo App): emulador boota sozinho, instala, executa, screenshots |
| **F4 iOS** | device_ios (simctl), XCUITest, validação build de simulador | Mesmo fluxo com `.zip` de `.app`; erro claro p/ ipa de device |
| **F5 MCP** | mcp_server em `/mcp` | Adicionar no Claude Code e disparar `run_test` + `get_report` |
| **F6 A2A** | a2a_server + AgentCard | AgentCard resolvável; roundtrip de task via client a2a-sdk |
| **F7 Polish** | launchd, prune, README bilíngue, custo/tokens no relatório, tap Homebrew, repositório público (MIT), instalador .pkg/.dmg | Sobrevive a reboot; `argus-doctor` verde; CI completa; `brew install andersontizaias/argus/argus-agent` funciona sem token |

## Riscos e mitigação

1. **Emuladores frágeis/lentos** — ficam de pé entre runs; snapshot de boot do AVD; health-check + 1 auto-repair; `error` ≠ `failed` no relatório
2. **Custo de tokens** — contexto zerado por passo; snapshots texto (não imagem); tokens/custo por run gravados e exibidos
3. **Flakiness de UI** — retry 1x com re-snapshot; `wait_for` explícita no prompt da persona; `attempts` por passo
4. **Tool-calling do modelo** — schemas mínimos, refs curtas, limite 8 iterações/passo, "testar provider" valida function-calling
5. **Setup nativo frágil** — `argus-doctor`/`/api/health` como fonte de verdade na UI; bootstrap idempotente; drivers pinados
6. **Segredos** — massa cifrada em repouso e redigida em logs/eventos; gitleaks na CI; nunca imprimir .env
7. **Concorrência** — `max_concurrent_runs` no claim do worker (1 mobile, 2 web)
