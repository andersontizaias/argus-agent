<p align="center">
  <img src="frontend/public/img/logo.png" alt="Argus Agent" width="220">
</p>

# Argus Agent

Agente de QA autônomo com persona de "QA sênior extremamente eficiente" — executa testes de aplicações **web**, **Android** e **iOS** a partir de um script BDD (Gherkin) e uma massa de testes, dirigindo a aplicação de verdade (Playwright para web, Appium para mobile) e produzindo relatórios com evidências por cenário.

Veja o plano completo em [`PLANO.md`](./PLANO.md).

## Status

🚧 Em desenvolvimento — Fase F0 (Fundação): backend (FastAPI + SQLite), frontend (React + Tailwind) e configuração de provider LLM.

## Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy + Alembic (SQLite), LangGraph
- **Frontend**: React 19, Vite, TypeScript, Tailwind v4
- **Automação**: Playwright (web), Appium (Android/iOS)
- **Integração**: API REST, MCP server, A2A

## Desenvolvimento

```bash
# Backend
uv sync
cp .env.example .env  # preencha ARGUS_SECRET_KEY
uv run alembic upgrade head
uv run argus

# Frontend (outro terminal)
cd frontend
npm install
npm run dev
```

Setup completo (Playwright, Android SDK, Appium, Xcode) via `scripts/bootstrap.sh` (fase F0, em progresso).

## Testes

```bash
uv run pytest --cov
cd frontend && npm run test:coverage
```
