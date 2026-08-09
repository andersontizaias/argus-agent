#!/bin/bash
# Argus Agent — parte visual do instalador (sempre rodando como o usuário
# do console, nunca como root — ver comentário em ./postinstall). Pede o
# GitHub token por uma caixa de diálogo nativa e abre uma janela do Terminal
# rodando install.sh + bootstrap.sh — o pacote .pkg não instala nada
# sozinho, só dá o empurrão inicial visual pra quem não quer copiar/colar
# comandos.
set -euo pipefail

INSTALL_DIR="${HOME}/argus"

TOKEN="$(osascript <<'OSA' 2>/dev/null || true
try
  set theToken to text returned of (display dialog "Argus Agent needs a read-only GitHub token for the private repository (classic Personal Access Token, 'repo' scope)." default answer "" with hidden answer with title "Argus Agent Setup" buttons {"Cancel", "Continue"} default button "Continue" cancel button "Cancel")
  return theToken
on error
  return ""
end try
OSA
)"

if [[ -z "${TOKEN}" ]]; then
  osascript -e 'display alert "Argus Agent" message "Setup cancelled — no token was provided. Run the installer again once you have one (see the repository README)." as warning' || true
  exit 1
fi

TOKEN_FILE="$(mktemp -t argus-token)"
chmod 600 "${TOKEN_FILE}"
printf '%s' "${TOKEN}" > "${TOKEN_FILE}"

# Script que a janela do Terminal roda de verdade. Lê o token de um arquivo
# com permissão restrita (nunca aparece na linha de comando visível nem no
# histórico do shell) e apaga tanto o arquivo do token quanto a si mesmo ao
# terminar.
RUNNER="$(mktemp -t argus-runner).sh"
cat > "${RUNNER}" <<EOF
#!/bin/bash
set -e
export GITHUB_TOKEN="\$(cat '${TOKEN_FILE}')"
rm -f '${TOKEN_FILE}'
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
