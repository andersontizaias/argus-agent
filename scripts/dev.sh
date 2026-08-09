#!/usr/bin/env bash
# Argus Agent — sobe API + worker + frontend (Vite dev server) juntos, pra
# desenvolvimento local. Ctrl+C derruba os três. Assume que
# scripts/bootstrap.sh já rodou (uv sync, npm install, .env, migrações).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

pids=()
cleanup() {
  echo
  echo "Shutting down..."
  for pid in "${pids[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "== argus (API + UI at http://127.0.0.1:8765) =="
uv run argus &
pids+=("$!")

echo "== argus-worker =="
uv run argus-worker &
pids+=("$!")

echo "== frontend (Vite dev server) =="
(cd frontend && npm run dev) &
pids+=("$!")

wait
