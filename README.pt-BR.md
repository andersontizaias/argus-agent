<p align="center">
  <img src="frontend/public/img/logo.png" alt="Argus Agent" width="220">
</p>

# 👁️ Argus Agent

**Agente de QA autônomo** com persona de "QA sênior extremamente eficiente" — executa testes de aplicações **web**, **Android** e **iOS** a partir de um script BDD (Gherkin) e uma massa de testes, dirigindo a aplicação de verdade (Playwright para web, Appium para mobile) e produzindo relatórios com evidências por cenário.

![CI](https://github.com/andersontizaias/argus-agent/actions/workflows/ci.yml/badge.svg)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.139+-009688?logo=fastapi)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-1C3C3C)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)
![Licença: MIT](https://img.shields.io/badge/License-MIT-green)

**Idioma:** 🇧🇷 Português (você está aqui) · [🇺🇸 English](README.md)

---

## 📑 Índice

- [✨ O que é?](#-o-que-é)
- [🛠️ Stack](#-stack)
- [📦 Instalação](#-instalação)
  - [🍺 Homebrew (recomendado)](#-homebrew-recomendado)
  - [📥 Tarball + install.sh](#-tarball--installsh)
  - [🧑‍💻 Checkout de desenvolvimento](#-checkout-de-desenvolvimento)
  - [🧙 Instalador com wizard (.pkg/.dmg, experimental)](#-instalador-com-wizard-pkgdmg-experimental)
- [🚀 Rodando](#-rodando)
- [🔁 LaunchAgents (subir sozinho no login)](#-launchagents-subir-sozinho-no-login)
- [📖 Uso](#-uso)
  - [📡 API REST](#-api-rest)
  - [🔌 MCP](#-mcp)
  - [🤝 A2A](#-a2a)
- [⚙️ Configuração](#-configuração)
- [📊 Relatórios](#-relatórios)
- [🧪 Testes](#-testes)
- [🌱 Contribuindo](#-contribuindo)
- [📄 Licença](#-licença)

---

## ✨ O que é?

Instalado nativamente num Mac (sem Docker no caminho crítico — o simulador de iOS não roda em container), o Argus Agent fala três protocolos de integração: **API REST**, **MCP** e **A2A**. Aponte para uma aplicação-alvo (URL web ou binário mobile), dê a ele um script BDD e uma massa de testes, e ele dirige a aplicação de verdade — browser via Playwright, emulador Android ou simulador iOS via Appium — produzindo um relatório por cenário com screenshots e logs.

Pra notas de arquitetura e decisões de design, veja [`PLANO.md`](./PLANO.md) *(diário de desenvolvimento)*.

## 🛠️ Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy + Alembic (SQLite WAL), LangGraph
- **Frontend**: React 19, Vite, TypeScript, Tailwind v4
- **Automação**: Playwright (web), Appium — UiAutomator2 (Android) e XCUITest (iOS)
- **Integração**: API REST (`X-API-Key`), MCP (Streamable HTTP em `/mcp`), A2A (`/a2a` + AgentCard)

## 📦 Instalação

### 🍺 Homebrew (recomendado)

```bash
brew tap andersontizaias/argus
brew install andersontizaias/argus/argus-agent
```

A primeira chamada de `argus`/`argus-worker`/`argus-doctor` faz o setup de verdade (`uv sync` + Playwright Chromium, ~200 MB, alguns minutos) num venv em `~/.argus/venv` — as próximas são instantâneas. Depois, veja [Rodando](#-rodando) e, se quiser que suba sozinho no login, [LaunchAgents](#-launchagents-subir-sozinho-no-login).

### 📥 Tarball + install.sh

Alternativa ao Homebrew — baixa a release mais recente e prepara tudo em `~/argus`:

```bash
curl -fsSL https://raw.githubusercontent.com/andersontizaias/argus-agent/main/scripts/install.sh | bash
```

Rodar de novo atualiza para a versão mais recente sem tocar em `~/.argus/` (banco, artefatos, `.env`).

### 🧑‍💻 Checkout de desenvolvimento

```bash
git clone git@github.com:andersontizaias/argus-agent.git
cd argus-agent
./scripts/bootstrap.sh   # idempotente: Homebrew, uv, node@22, Android/iOS
                          # (checa e instrui, nunca baixa GB sozinho), Appium,
                          # uv sync, Playwright, .env, migrações, build do
                          # frontend — termina com um resumo do `argus-doctor`
```

### 🧙 Instalador com wizard (.pkg/.dmg, experimental)

Uma versão visual, de duplo clique, da instalação por tarball acima — abre
uma janela do Terminal e roda o mesmo `install.sh`/`bootstrap.sh`,
visivelmente. Baixe o `ArgusAgent-Installer.dmg` na
[release mais recente](https://github.com/andersontizaias/argus-agent/releases/latest)
(compilado e anexado automaticamente pelo `release.yml`). Ainda não
assinado/notarizado, então o Gatekeeper pode avisar no primeiro uso — veja
[`packaging/macos/README.md`](./packaging/macos/README.md) pra detalhes e
contornos.

## 🚀 Rodando

```bash
uv run argus           # API + UI em http://127.0.0.1:8765
uv run argus-worker    # processa as execuções (outro terminal)
```

Ou os dois + o Vite dev server juntos, num checkout de desenvolvimento:

```bash
./scripts/dev.sh
```

`GET /api/health` (e `uv run argus-doctor` na mesma lógica) reporta o estado de cada dependência nativa — banco, disco, Playwright, `adb`/`emulator`, `xcrun`, Appium.

## 🔁 LaunchAgents (subir sozinho no login)

```bash
./scripts/launchd/install.sh     # registra argus + argus-worker como LaunchAgents
./scripts/launchd/uninstall.sh   # remove
```

O `launchd` sobe os dois processos no login e reinicia se caírem (`KeepAlive`) — sem precisar de um terminal aberto. Logs em `~/.argus/logs/`.

## 📖 Uso

1. Abra `http://127.0.0.1:8765`, configure um provider de LLM em **Config** (chave testável na hora) e, se for usar a API fora da UI, gere uma **API key**.
2. Em **Nova Execução**, escolha a plataforma (web via URL, Android/iOS via binário), cole o script BDD e a massa de testes.
3. Acompanhe ao vivo em **Detalhe da Run** (cenários/passos mudando de estado, screenshots) ou via API.

### 📡 API REST

`POST /api/runs` · `GET /api/runs` · `GET /api/runs/{id}` · `POST /api/runs/{id}/cancel` · `GET /api/runs/{id}/stream` (SSE) · `GET /api/runs/{id}/report[.html]` · `GET /api/runs/{id}/artifacts.zip` · `GET /api/evidences/{id}` · `GET`/`POST /api/config` · `POST /api/config/test-llm-provider/{id}` · CRUD `/api/api-keys` · `GET /api/health`.

Autenticação por `X-API-Key: argus_<prefix>_<random>` (exibida uma vez na criação). Fluxo típico de CI: `POST /api/runs` → poll/SSE → exit code pelo `status` final → baixa `report.json`.

### 🔌 MCP

Servidor Streamable HTTP em `/mcp`. Tools: `run_test`, `get_run_status`, `get_report`, `list_runs`, `cancel_run`.

```bash
claude mcp add --transport http argus http://127.0.0.1:8765/mcp -H "X-API-Key: argus_..."
```

### 🤝 A2A

AgentCard em `/.well-known/agent-card.json`, rota `/a2a`. Skill `execute_qa_test` — envia a run como uma Message com uma Part de dados (JSON) e acompanha via streaming de status.

## ⚙️ Configuração

Variáveis de ambiente (`.env`, ver [`.env.example`](./.env.example)): `ARGUS_SECRET_KEY` (chave Fernet — cifra credenciais em repouso), `ARGUS_DB_PATH`, `ARGUS_ARTIFACTS_DIR`, `ARGUS_HOST`/`ARGUS_PORT`, `ARGUS_REQUIRE_API_KEY`, `APPIUM_BASE_PORT`, `ARGUS_ANDROID_AVD`/`ARGUS_ANDROID_EMULATOR_PORT`, `ARGUS_IOS_DEVICE`.

Provider de LLM, secrets de binário e retenção de relatórios (`retention_days`, 30 dias por padrão — `0` desliga o prune) ficam em `/api/config`, editáveis pela UI.

## 📊 Relatórios

`~/.argus/artifacts/{run_id}/`: `report.json`, `report.html` (abre offline), `screenshots/`, `logs/agent.log` (massa de testes redigida — valores viram `***`). Cada relatório traz tokens de entrada/saída e custo estimado da run. Runs terminadas mais antigas que a retenção configurada são apagadas automaticamente pelo worker.

## 🧪 Testes

```bash
uv run pytest --cov
cd frontend && npm run test:coverage
```

CI (`ci.yml`) roda ruff, mypy, pytest (cobertura ≥90%), complexidade (`xenon`), duplicação (`jscpd`), segurança (`pip-audit`, `npm audit`, gitleaks) e o build+testes do frontend. Releases (`release.yml`) disparam em tag `v*`, publicando o tarball + `install.sh` na GitHub Release.

## 🌱 Contribuindo

Veja [`CONTRIBUTING.md`](./CONTRIBUTING.md) *(em inglês)* pro modelo de branches e como uma mudança vai de um PR até virar release publicada.

## 📄 Licença

[MIT](./LICENSE)
