#!/bin/bash
# Argus Agent — parte visual do instalador (sempre rodando como o usuário
# do console, nunca como root — ver comentário em ./postinstall). Abre uma
# janela do Terminal rodando install.sh + bootstrap.sh — o pacote .pkg não
# instala nada sozinho, só dá o empurrão inicial visual pra quem não quer
# copiar/colar comandos.
set -euo pipefail

INSTALL_DIR="${HOME}/argus"

# Script que a janela do Terminal roda de verdade — o mesmo caminho de uma
# instalação manual (repo público, sem token necessário). Apaga a si mesmo
# ao terminar.
RUNNER="$(mktemp -t argus-runner).sh"
cat > "${RUNNER}" <<EOF
#!/bin/bash
set -e
export ARGUS_INSTALL_DIR="${INSTALL_DIR}"
echo "== Argus Agent — downloading and installing =="
echo
curl -fsSL https://raw.githubusercontent.com/andersontizaias/argus-agent/main/scripts/install.sh | bash
echo
cd "${INSTALL_DIR}"
./scripts/bootstrap.sh
echo

# Sobe a app e abre o navegador — só faz sentido aqui, no wizard visual
# (install.sh/bootstrap.sh sozinhos não devem abrir GUI, são usados também
# por script/CI). Idempotente: se já tiver algo respondendo em :8765 (outra
# instalação, ou uma execução anterior do wizard), não sobe de novo.
if curl -s -o /dev/null http://127.0.0.1:8765/api/health; then
  echo "Argus Agent is already running."
else
  echo "== Starting Argus Agent =="
  mkdir -p "${HOME}/.argus/logs"
  nohup uv run argus > "${HOME}/.argus/logs/argus.log" 2>&1 &
  disown
  nohup uv run argus-worker > "${HOME}/.argus/logs/argus-worker.log" 2>&1 &
  disown
  echo "Waiting for it to come up..."
  for _ in \$(seq 1 30); do
    curl -s -o /dev/null http://127.0.0.1:8765/api/health && break
    sleep 1
  done
fi

open http://127.0.0.1:8765

echo
echo "Argus Agent keeps running in the background after you close this window"
echo "(logs at ~/.argus/logs/). To stop it: pkill -f 'uv run argus'"
echo "To have it start automatically on every login instead, run:"
echo "  cd ${INSTALL_DIR} && ./scripts/launchd/install.sh"
echo
echo "Press Return to close this window."
read -r
rm -f "\$0"
EOF
chmod +x "${RUNNER}"

osascript -e "tell application \"Terminal\" to activate" -e "tell application \"Terminal\" to do script \"${RUNNER}\""
