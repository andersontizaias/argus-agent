<p align="center">
  <img src="frontend/public/img/logo.png" alt="Argus Agent" width="220">
</p>

# 👁️ Argus Agent

**Autonomous QA agent** with the persona of an "extremely efficient senior QA" — runs tests for **web**, **Android** and **iOS** apps from a BDD (Gherkin) script and a test data set, driving the real application (Playwright for web, Appium for mobile) and producing per-scenario reports with evidence.

![CI](https://github.com/andersontizaias/argus-agent/actions/workflows/ci.yml/badge.svg)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.139+-009688?logo=fastapi)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-1C3C3C)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)
![Private repo](https://img.shields.io/badge/repo-private-lightgrey)

**Language:** [🇧🇷 Português](README.pt-BR.md) · 🇺🇸 English (you are here)

---

## 📑 Table of Contents

- [✨ What is it?](#-what-is-it)
- [🛠️ Tech Stack](#-tech-stack)
- [📦 Installation](#-installation)
  - [🍺 Homebrew (recommended)](#-homebrew-recommended)
  - [📥 Tarball + install.sh](#-tarball--installsh)
  - [🧑‍💻 Development checkout](#-development-checkout)
- [🚀 Running](#-running)
- [🔁 LaunchAgents (start on login)](#-launchagents-start-on-login)
- [📖 Usage](#-usage)
  - [📡 REST API](#-rest-api)
  - [🔌 MCP](#-mcp)
  - [🤝 A2A](#-a2a)
- [⚙️ Configuration](#-configuration)
- [📊 Reports](#-reports)
- [🧪 Tests](#-tests)

---

## ✨ What is it?

Installed natively on a Mac (no Docker on the critical path — the iOS simulator doesn't run in a container), Argus Agent speaks three integration protocols: **REST API**, **MCP** and **A2A**. Point it at a target application (a web URL or a mobile binary), give it a BDD script and test data, and it drives the app for real — a browser via Playwright, an Android emulator or iOS simulator via Appium — producing a report per scenario with screenshots and logs.

Development went through phases F0–F7 (foundation, web agent, REST + UI, Android, iOS, MCP, A2A, and final polish — LaunchAgents, retention/prune, token/cost tracking, private Homebrew tap). See the full plan (architecture, technical decisions, phase-by-phase verification) in [`PLANO.md`](./PLANO.md) *(pt-BR only)*.

## 🛠️ Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy + Alembic (SQLite WAL), LangGraph
- **Frontend**: React 19, Vite, TypeScript, Tailwind v4
- **Automation**: Playwright (web), Appium — UiAutomator2 (Android) and XCUITest (iOS)
- **Integration**: REST API (`X-API-Key`), MCP (Streamable HTTP at `/mcp`), A2A (`/a2a` + AgentCard)

## 📦 Installation

Private repository — every path below except the dev checkout needs a GitHub token with read access to the repo: a **classic** PAT with the **`repo`** scope (not `read:packages` — that's for GitHub Packages, a different resource — and not fine-grained, untested here).

### 🍺 Homebrew (recommended)

```bash
export HOMEBREW_GITHUB_API_TOKEN=ghp_xxx   # read-only token for the private repo
brew tap andersontizaias/argus
brew install argus
```

The first call to `argus`/`argus-worker`/`argus-doctor` does the real setup (`uv sync` + Playwright Chromium, ~200 MB, a few minutes) into a venv at `~/.argus/venv` — later calls are instant. Then see [Running](#-running) and, if you want it to start on login, [LaunchAgents](#-launchagents-start-on-login).

To bump the formula for a new release, edit `url`/`version`/`sha256` in the [tap](https://github.com/andersontizaias/homebrew-argus).

### 📥 Tarball + install.sh

An alternative to Homebrew — downloads the latest release and sets everything up in `~/argus`:

```bash
curl -fsSL https://raw.githubusercontent.com/andersontizaias/argus-agent/main/scripts/install.sh -o install.sh
GITHUB_TOKEN=ghp_xxx bash install.sh
```

Running it again updates to the latest version without touching `~/.argus/` (database, artifacts, `.env`).

### 🧑‍💻 Development checkout

```bash
git clone git@github.com:andersontizaias/argus-agent.git
cd argus-agent
./scripts/bootstrap.sh   # idempotent: Homebrew, uv, node@22, Android/iOS
                          # (checks and instructs, never downloads GBs on its
                          # own), Appium, uv sync, Playwright, .env,
                          # migrations, frontend build — ends with an
                          # `argus-doctor` summary
```

## 🚀 Running

```bash
uv run argus           # API + UI at http://127.0.0.1:8765
uv run argus-worker    # processes runs (separate terminal)
```

Or both plus the Vite dev server together, from a development checkout:

```bash
./scripts/dev.sh
```

`GET /api/health` (and `uv run argus-doctor`, same logic) reports the state of every native dependency — database, disk, Playwright, `adb`/`emulator`, `xcrun`, Appium.

## 🔁 LaunchAgents (start on login)

```bash
./scripts/launchd/install.sh     # registers argus + argus-worker as LaunchAgents
./scripts/launchd/uninstall.sh   # removes them
```

`launchd` starts both processes on login and restarts them if they crash (`KeepAlive`) — no open terminal needed. Logs at `~/.argus/logs/`.

## 📖 Usage

1. Open `http://127.0.0.1:8765`, set up an LLM provider in **Config** (testable on the spot) and, if you'll use the API outside the UI, generate an **API key**.
2. In **New Run**, pick the platform (web via URL, Android/iOS via a binary), paste the BDD script and the test data.
3. Follow along live in **Run Detail** (scenarios/steps changing state, screenshots) or via the API.

### 📡 REST API

`POST /api/runs` · `GET /api/runs` · `GET /api/runs/{id}` · `POST /api/runs/{id}/cancel` · `GET /api/runs/{id}/stream` (SSE) · `GET /api/runs/{id}/report[.html]` · `GET /api/runs/{id}/artifacts.zip` · `GET /api/evidences/{id}` · `GET`/`POST /api/config` · `POST /api/config/test-llm-provider/{id}` · CRUD `/api/api-keys` · `GET /api/health`.

Auth via `X-API-Key: argus_<prefix>_<random>` (shown once on creation). Typical CI flow: `POST /api/runs` → poll/SSE → exit code from the final `status` → download `report.json`.

### 🔌 MCP

Streamable HTTP server at `/mcp`. Tools: `run_test`, `get_run_status`, `get_report`, `list_runs`, `cancel_run`.

```bash
claude mcp add --transport http argus http://127.0.0.1:8765/mcp -H "X-API-Key: argus_..."
```

### 🤝 A2A

AgentCard at `/.well-known/agent-card.json`, route `/a2a`. Skill `execute_qa_test` — send the run as a Message with one data Part (JSON) and follow along via status streaming.

## ⚙️ Configuration

Environment variables (`.env`, see [`.env.example`](./.env.example)): `ARGUS_SECRET_KEY` (Fernet key — encrypts credentials at rest), `ARGUS_DB_PATH`, `ARGUS_ARTIFACTS_DIR`, `ARGUS_HOST`/`ARGUS_PORT`, `ARGUS_REQUIRE_API_KEY`, `APPIUM_BASE_PORT`, `ARGUS_ANDROID_AVD`/`ARGUS_ANDROID_EMULATOR_PORT`, `ARGUS_IOS_DEVICE`.

LLM provider, binary-source secrets and report retention (`retention_days`, 30 days by default — `0` disables pruning) live in `/api/config`, editable from the UI.

## 📊 Reports

`~/.argus/artifacts/{run_id}/`: `report.json`, `report.html` (opens offline), `screenshots/`, `logs/agent.log` (test data redacted — values become `***`). Every report includes input/output token counts and the run's estimated cost. Terminated runs older than the configured retention are automatically pruned by the worker.

## 🧪 Tests

```bash
uv run pytest --cov
cd frontend && npm run test:coverage
```

CI (`ci.yml`) runs ruff, mypy, pytest (coverage ≥90%), complexity (`xenon`), duplication (`jscpd`), security (`pip-audit`, `npm audit`, gitleaks) and the frontend build+tests. Releases (`release.yml`) trigger on `v*` tags, publishing the tarball + `install.sh` to the GitHub Release.
