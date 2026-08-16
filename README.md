<p align="center">
  <img src="frontend/public/img/logo.png" alt="Argus Agent" width="220">
</p>

# 👁️ Argus Agent

**Autonomous QA agent** with the persona of an "extremely efficient senior QA" — runs tests for **web**, **Android** and **iOS** apps from a BDD (Gherkin) script and a test data set, driving the real application (Playwright for web, Appium for mobile) and producing per-scenario reports with evidence. For apps with no test coverage yet, **Explore mode** flips this around: point Argus at the app with no script at all and it navigates on its own, then generates a candidate `.feature` (plus a session video) to bootstrap a regression suite.

![CI](https://github.com/andersontizaias/argus-agent/actions/workflows/ci.yml/badge.svg)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.139+-009688?logo=fastapi)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-1C3C3C)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)
![License: MIT](https://img.shields.io/badge/License-MIT-green)

**Language:** [🇧🇷 Português](README.pt-BR.md) · 🇺🇸 English (you are here)

---

## 📑 Table of Contents

- [✨ What is it?](#-what-is-it)
- [🛠️ Tech Stack](#-tech-stack)
- [📦 Installation](#-installation)
  - [🍺 Homebrew (recommended)](#-homebrew-recommended)
  - [📥 Tarball + install.sh](#-tarball--installsh)
  - [🧑‍💻 Development checkout](#-development-checkout)
  - [🧙 Installer wizard (.pkg/.dmg, experimental)](#-installer-wizard-pkgdmg-experimental)
- [🚀 Running](#-running)
- [🔁 LaunchAgents (start on login)](#-launchagents-start-on-login)
- [📖 Usage](#-usage)
  - [📱 Mobile binaries](#-mobile-binaries)
  - [🧭 Explore mode](#-explore-mode)
  - [📡 REST API](#-rest-api)
  - [🔌 MCP](#-mcp)
  - [🤝 A2A](#-a2a)
- [⚙️ Configuration](#-configuration)
- [📊 Reports](#-reports)
- [🧪 Tests](#-tests)
- [🌱 Contributing](#-contributing)
- [📄 License](#-license)

---

## ✨ What is it?

Installed natively on a Mac (no Docker on the critical path — the iOS simulator doesn't run in a container), Argus Agent speaks three integration protocols: **REST API**, **MCP** and **A2A**. Point it at a target application (a web URL or a mobile binary), give it a BDD script and test data, and it drives the app for real — a browser via Playwright, an Android emulator or iOS simulator via Appium — producing a report per scenario with screenshots and logs.

For architecture notes and design decisions, see [`PLANO.md`](./PLANO.md) *(development log, pt-BR only)*.

## 🛠️ Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy + Alembic (SQLite WAL), LangGraph
- **Frontend**: React 19, Vite, TypeScript, Tailwind v4
- **Automation**: Playwright (web), Appium — UiAutomator2 (Android) and XCUITest (iOS), ffmpeg (remuxes Explore-mode mobile session videos for browser playback)
- **Integration**: REST API (`X-API-Key`), MCP (Streamable HTTP at `/mcp`), A2A (`/a2a` + AgentCard)

## 📦 Installation

### 🍺 Homebrew (recommended)

```bash
brew tap andersontizaias/argus
brew install andersontizaias/argus/argus-agent
```

The first call to `argus`/`argus-worker`/`argus-doctor` does the real setup (`uv sync` + Playwright Chromium, ~200 MB, a few minutes) into a venv at `~/.argus/venv` — later calls are instant. Then see [Running](#-running) and, if you want it to start on login, [LaunchAgents](#-launchagents-start-on-login).

### 📥 Tarball + install.sh

An alternative to Homebrew — downloads the latest release and sets everything up in `~/argus`:

```bash
curl -fsSL https://raw.githubusercontent.com/andersontizaias/argus-agent/main/scripts/install.sh | bash
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

### 🧙 Installer wizard (.pkg/.dmg, experimental)

A double-click, GUI version of the tarball install above — opens a
Terminal window and runs the same `install.sh`/`bootstrap.sh`, visibly.
Download `ArgusAgent-Installer.dmg` from the [latest release](https://github.com/andersontizaias/argus-agent/releases/latest)
(built and attached automatically by `release.yml`). Not signed/notarized
yet, so Gatekeeper may warn on first open — see
[`packaging/macos/README.md`](./packaging/macos/README.md) for details
and mitigations.

## 🚀 Running

```bash
uv run argus           # API + UI at http://127.0.0.1:8765
uv run argus-worker    # processes runs (separate terminal)
```

Or both plus the Vite dev server together, from a development checkout:

```bash
./scripts/dev.sh
```

`GET /api/health` (and `uv run argus-doctor`, same logic) reports the state of every native dependency — database, disk, Playwright, `adb`/`emulator`, `xcrun`, Appium, `ffmpeg` (remuxes mobile Explore-mode session videos to "faststart" so they stream in the browser right after recording — see `_remux_faststart` in `src/agent/nodes.py`; missing `ffmpeg` degrades gracefully, the video is still saved and downloadable, just not playable inline).

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

### 📱 Mobile binaries

`binary_url` (Android/iOS runs) accepts a real `http(s)` URL — optionally protected, set `binary_auth_secret` to the name of a secret registered in **Config** and it's sent as a Bearer token — or a local file: uploaded straight from **New Run**, or referenced by an absolute path/`file://` if it's already on the machine running Argus.

- **Android**: a plain `.apk`. Only have an `.aab`? Build a universal `.apk` from it first (`bundletool build-apks --mode=universal`) — Argus doesn't install `.aab` directly.
- **iOS**: a `.zip` containing a **Simulator build** of the `.app` (`Payload/<Name>.app/`), not a device `.ipa` — only the Simulator is supported, no physical device yet. What matters is the content, not the file extension: the `.app`'s `Info.plist` must have `iPhoneSimulator` in `CFBundleSupportedPlatforms`, so a zip named `.ipa` works fine as long as what's inside was built for the Simulator SDK. Most `.ipa`s you already have lying around (TestFlight, App Store, Ad Hoc) are device builds and get rejected with a clear error instead of failing cryptically mid-run.
  Typical way to produce one: `xcodebuild ... -sdk iphonesimulator -derivedDataPath build` (or `fastlane gym`/`build_app` with `destination: "generic/platform=iOS Simulator"`, `skip_package_ipa: true`), then zip the result: `ditto -c -k --sequesterRsrc --keepParent build/.../YourApp.app YourApp.zip`.

### 🧭 Explore mode

For a project with no BDD coverage yet, **New Run → Mode → Explore** skips the script entirely: point it at a web URL or a mobile binary, confirm the checkbox that the target **isn't production** (required — Argus acts on its own, with no human-written step to follow), and it navigates the app by itself, one action at a time, deciding what to click/tap/fill next based on what's on screen. When it runs out of new ground to cover (or hits the action budget, default 25, max 100), a separate synthesis call turns the trace into a candidate `.feature` (validated against the same Gherkin parser used for regular runs) for you to review, edit and reuse as a normal Execute run (**Use in New Run** on the Run Detail page pre-fills the script).

Also recorded: a video of the whole session (Playwright's native recorder for web; Appium's `start_recording_screen` for mobile, forced to `libx264`/`yuv420p` and remuxed "faststart" after saving — see `_maybe_start_mobile_recording`/`_remux_faststart` in `src/agent/nodes.py` — so it streams in the browser right away instead of only after a full download) — useful to double-check what the agent actually did beyond what made it into the `.feature`.

Guardrails are enforced in **code**, not just prompted: a denylist blocks tapping/clicking anything that looks like a real-effect action (delete, pay, submit, checkout, cancel subscription — pt+en), and web navigation is restricted to the run's starting origin. A blocked action shows up as a skipped note in the generated script instead of silently failing the run.

Exploration quality tracks the LLM's agentic reliability more than its raw capability — a small/local model (e.g. Ollama) tends to loop on the same screen or misjudge whether a tap had any effect noticeably more often than a frontier hosted model; if the generated script looks too shallow, a stronger provider is usually the fix, not a bigger action budget. `mode`/`max_actions`/`confirmed_non_production` are REST-API-only for now — MCP's `run_test` and the A2A skill still cover Execute mode only.

### 📡 REST API

`POST /api/runs` · `GET /api/runs` · `GET /api/runs/{id}` · `POST /api/runs/{id}/cancel` · `GET /api/runs/{id}/stream` (SSE) · `GET /api/runs/{id}/report[.html]` · `GET /api/runs/{id}/artifacts.zip` · `GET /api/evidences/{id}` · `POST /api/binaries/upload` · `GET`/`POST /api/config` · `POST /api/config/test-llm-provider/{id}` · CRUD `/api/api-keys` · `GET /api/health`.

`POST /api/runs` body: `platform`, `mode` (`"execute"` default, or `"explore"` — see [Explore mode](#-explore-mode)), `bdd_script`/`test_data` (required for `execute`, omitted for `explore`), `app_url`/`binary_url`/`binary_auth_secret`, `llm_provider`/`llm_model` (falls back to the configured default), and, for `explore`: `max_actions` (1–100, default 25) and `confirmed_non_production` (must be `true`).

Auth via `X-API-Key: argus_<prefix>_<random>` (shown once on creation). Typical CI flow: `POST /api/runs` → poll/SSE → exit code from the final `status` → download `report.json`.

### 🔌 MCP

Streamable HTTP server at `/mcp`. Tools: `run_test`, `get_run_status`, `get_report`, `list_runs`, `cancel_run`.

```bash
claude mcp add --transport http argus http://127.0.0.1:8765/mcp -H "X-API-Key: argus_..."
```

### 🤝 A2A

AgentCard at `/.well-known/agent-card.json`, route `/a2a`. Skill `execute_qa_test` — send the run as a Message with one data Part (JSON) and follow along via status streaming.

## ⚙️ Configuration

Environment variables (`.env`, see [`.env.example`](./.env.example)): `ARGUS_SECRET_KEY` (Fernet key — encrypts credentials at rest), `ARGUS_DB_PATH`, `ARGUS_ARTIFACTS_DIR`, `ARGUS_UPLOADS_DIR`, `ARGUS_HOST`/`ARGUS_PORT`, `ARGUS_REQUIRE_API_KEY`, `APPIUM_BASE_PORT`, `ARGUS_ANDROID_AVD`/`ARGUS_ANDROID_EMULATOR_PORT`, `ARGUS_IOS_DEVICE`.

LLM providers, binary-source secrets and report retention (`retention_days`, 30 days by default — `0` disables pruning) live in `/api/config`, editable from the UI. Each provider keeps its own API key and default model side by side (picking a "default provider" doesn't make you lose the model you had configured for another one); AWS Bedrock additionally accepts either a bearer API key (short- or long-lived) or classic IAM access key/secret/session-token credentials.

## 📊 Reports

`~/.argus/artifacts/{run_id}/`: `report.json`, `report.html` (opens offline), `screenshots/`, `logs/agent.log` (test data redacted — values become `***`). Every report includes input/output token counts and the run's estimated cost. Explore-mode runs additionally get `video/exploracao.mp4` (the session recording, see [Explore mode](#-explore-mode)) and the generated `.feature` text, both surfaced in the report and on the Run Detail page instead of a scenario list. Terminated runs older than the configured retention are automatically pruned by the worker.

## 🧪 Tests

```bash
uv run pytest --cov
cd frontend && npm run test:coverage
```

CI (`ci.yml`) runs ruff, mypy, pytest (coverage ≥90%), complexity (`xenon`), duplication (`jscpd`), security (`pip-audit`, `npm audit`, gitleaks) and the frontend build+tests (coverage ≥90% too). Releases (`release.yml`) trigger on merges into `main` — it reads the version straight from `pyproject.toml` and only publishes if that version doesn't have a tag yet, so a merge without a version bump is a no-op. Publishes the tarball + `install.sh` and, on a separate macOS job, the `.dmg` installer, to the GitHub Release. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the full branch → release flow.

## 🌱 Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the branching model and how a change goes from a PR to a published release.

## 📄 License

[MIT](./LICENSE)
