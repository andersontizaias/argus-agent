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
echo "Press Return to close this window."
read -r
rm -f "\$0"
EOF
chmod +x "${RUNNER}"

osascript -e "tell application \"Terminal\" to activate" -e "tell application \"Terminal\" to do script \"${RUNNER}\""
