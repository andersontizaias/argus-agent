#!/usr/bin/env bash
# Argus Agent — remove os LaunchAgents instalados por install.sh. Não apaga
# ~/.argus/ (banco, artefatos, logs) nem o checkout do código — só para os
# processos e desliga o "sobe sozinho no login".
set -euo pipefail

AGENTS_DIR="${HOME}/Library/LaunchAgents"
UID_GUI="gui/$(id -u)"

API_LABEL="com.andersontizaias.argus-agent.api"
WORKER_LABEL="com.andersontizaias.argus-agent.worker"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Erro: launchd é específico do macOS." >&2
  exit 1
fi

echo "== Argus Agent — removendo LaunchAgents =="

for label in "${API_LABEL}" "${WORKER_LABEL}"; do
  plist="${AGENTS_DIR}/${label}.plist"
  launchctl bootout "${UID_GUI}/${label}" 2>/dev/null || true
  if [[ -f "${plist}" ]]; then
    rm -f "${plist}"
    echo "✓ ${label} removido"
  else
    echo "- ${label} não estava instalado"
  fi
done

echo
echo "Pronto. Os processos já em execução foram encerrados; nada mais sobe sozinho no login."
