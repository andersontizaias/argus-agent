#!/usr/bin/env bash
# Argus Agent — instala argus (API) e argus-worker como LaunchAgents do
# macOS: sobem sozinhos no login e o launchd os reinicia se caírem
# (KeepAlive) — sem precisar deixar um terminal aberto rodando `uv run`.
#
# Uso:
#   scripts/launchd/install.sh                # usa o diretório do próprio
#                                              # checkout como instalação
#   ARGUS_INSTALL_DIR=/outro/caminho scripts/launchd/install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_INSTALL_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INSTALL_DIR="${ARGUS_INSTALL_DIR:-${1:-${DEFAULT_INSTALL_DIR}}}"
LOG_DIR="${HOME}/.argus/logs"
AGENTS_DIR="${HOME}/Library/LaunchAgents"
UID_GUI="gui/$(id -u)"

API_LABEL="com.andersontizaias.argus-agent.api"
WORKER_LABEL="com.andersontizaias.argus-agent.worker"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Error: launchd is macOS-only." >&2
  exit 1
fi

UV_PATH="$(command -v uv || true)"
if [[ -z "${UV_PATH}" ]]; then
  echo "Error: 'uv' not found in PATH. Install it first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi
UV_BIN_DIR="$(dirname "${UV_PATH}")"

# launchd NÃO herda o PATH do shell interativo (sem .zshrc/.bashrc, sem
# nvm/volta) — só o que a gente põe explicitamente aqui. Sem isso, appium
# (normalmente instalado via `npm install -g`, num diretório gerenciado por
# nvm/Homebrew/etc.) fica invisível pro processo do launchd mesmo estando
# instalado — argus-doctor mostra "not found in PATH" mesmo com tudo certo
# (achado ao vivo). Resolve onde appium/node estão AGORA, no shell de quem
# instala, e grava o caminho absoluto no plist — falha graciosamente (Appium
# continua indisponível pra runs mobile) se nenhum dos dois estiver visível
# na hora do install, mas não impede web.
PATH_VALUE="${UV_BIN_DIR}"
for bin in appium node; do
  bin_path="$(command -v "${bin}" || true)"
  if [[ -n "${bin_path}" ]]; then
    bin_dir="$(dirname "${bin_path}")"
    case ":${PATH_VALUE}:" in
      *":${bin_dir}:"*) ;; # já incluído (ex.: appium e node no mesmo dir)
      *) PATH_VALUE="${PATH_VALUE}:${bin_dir}" ;;
    esac
  fi
done
PATH_VALUE="${PATH_VALUE}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if [[ ! -f "${INSTALL_DIR}/pyproject.toml" ]]; then
  echo "Error: ${INSTALL_DIR} doesn't look like an Argus Agent installation (no pyproject.toml)." >&2
  exit 1
fi

echo "== Argus Agent — installing LaunchAgents =="
echo "Install dir: ${INSTALL_DIR}"
echo "Logs:        ${LOG_DIR}"
echo "PATH:        ${PATH_VALUE}"
if ! command -v appium >/dev/null 2>&1; then
  echo "⚠ 'appium' not found in PATH right now — Android/iOS runs won't work" >&2
  echo "  until it's installed and the LaunchAgents are reinstalled (rerun this script)." >&2
fi
echo

mkdir -p "${LOG_DIR}" "${AGENTS_DIR}"

_render() {
  # sed com '|' como delimitador — os valores substituídos são paths, que
  # sempre contêm '/'.
  local template="$1" dest="$2"
  sed \
    -e "s|__UV_PATH__|${UV_PATH}|g" \
    -e "s|__UV_BIN_DIR__|${UV_BIN_DIR}|g" \
    -e "s|__PATH_VALUE__|${PATH_VALUE}|g" \
    -e "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
    -e "s|__HOME__|${HOME}|g" \
    -e "s|__LOG_DIR__|${LOG_DIR}|g" \
    "${template}" > "${dest}"
}

_install_agent() {
  local label="$1" template="$2"
  local dest="${AGENTS_DIR}/${label}.plist"
  _render "${template}" "${dest}"
  # bootout é best-effort — falha (job não carregado ainda) não deve
  # interromper o script; bootstrap/enable são os que precisam funcionar.
  launchctl bootout "${UID_GUI}/${label}" 2>/dev/null || true
  launchctl bootstrap "${UID_GUI}" "${dest}"
  launchctl enable "${UID_GUI}/${label}"
  echo "✓ ${label} installed and running (${dest})"
}

_install_agent "${API_LABEL}" "${SCRIPT_DIR}/com.andersontizaias.argus-agent.api.plist.template"
_install_agent "${WORKER_LABEL}" "${SCRIPT_DIR}/com.andersontizaias.argus-agent.worker.plist.template"

echo
echo "Done. Both processes will start automatically from the next login/reboot."
echo "  Check status: launchctl list | grep andersontizaias"
echo "  View logs:    tail -f ${LOG_DIR}/argus.log ${LOG_DIR}/argus-worker.log"
echo "  Uninstall:    scripts/launchd/uninstall.sh"
