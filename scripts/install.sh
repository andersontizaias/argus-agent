#!/usr/bin/env bash
# Argus Agent — instalador do client (macOS).
#
# Baixa a release mais recente do GitHub (repo privado — exige um token com
# permissão de leitura), extrai em ~/argus e prepara o backend (uv sync,
# Playwright, migração do banco). Rodar de novo atualiza para a versão mais
# recente sem tocar em ~/.argus/ (banco, artefatos, .env) — só o código em
# ~/argus é substituído.
#
# Uso:
#   GITHUB_TOKEN=ghp_xxx ./install.sh
# ou deixe o script pedir o token interativamente.
set -euo pipefail

REPO="andersontizaias/argus-agent"
INSTALL_DIR="${ARGUS_INSTALL_DIR:-$HOME/argus}"

echo "== Argus Agent installer =="
echo "Destination: $INSTALL_DIR"
echo

for bin in curl python3; do
  command -v "$bin" >/dev/null 2>&1 || { echo "Error: '$bin' not found in PATH." >&2; exit 1; }
done
if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' not found. Install it first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
  read -rsp "GitHub token (private repo, classic 'repo' scope — not 'read:packages', which is only for GitHub Packages, nor fine-grained): " GITHUB_TOKEN
  echo
fi
export GITHUB_TOKEN

TMP_TARBALL=""
RELEASE_JSON_FILE="$(mktemp -t argus-release-XXXXXX).json"
trap 'rm -f "${RELEASE_JSON_FILE}" "${TMP_TARBALL}"' EXIT

echo "Looking up the latest release..."
curl -sf \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -o "${RELEASE_JSON_FILE}" \
  "https://api.github.com/repos/${REPO}/releases/latest" \
  || { echo "Error: couldn't query the release (invalid token or no access to the repo?)." >&2; exit 1; }

# Lê de um arquivo (não interpola o JSON no código Python via shell) — evita
# quebrar com aspas/caracteres especiais que o GitHub decidir incluir.
read -r VERSION ASSET_URL < <(python3 -c "
import json
with open('${RELEASE_JSON_FILE}') as f:
    data = json.load(f)
tag = data.get('tag_name', '')
asset_url = ''
for asset in data.get('assets', []):
    name = asset.get('name', '')
    if name.startswith('argus-agent-') and name.endswith('.tar.gz'):
        asset_url = asset.get('url', '')
        break
print(tag, asset_url)
")

if [ -z "${ASSET_URL}" ]; then
  echo "Error: couldn't find the tarball in release ${VERSION:-unknown}." >&2
  exit 1
fi
echo "Version found: ${VERSION}"

TMP_TARBALL="$(mktemp -t argus-agent-XXXXXX).tar.gz"
echo "Downloading..."
curl -sfL \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H "Accept: application/octet-stream" \
  -o "${TMP_TARBALL}" \
  "${ASSET_URL}"

mkdir -p "${INSTALL_DIR}"
echo "Extracting to ${INSTALL_DIR}..."
tar -xzf "${TMP_TARBALL}" -C "${INSTALL_DIR}" --strip-components=1
rm -f "${TMP_TARBALL}"

cd "${INSTALL_DIR}"

echo "Installing Python dependencies (uv sync)..."
uv sync

echo "Installing Playwright's Chromium..."
uv run playwright install chromium

if [ ! -f .env ]; then
  echo "Generating .env with a new ARGUS_SECRET_KEY..."
  cp .env.example .env
  SECRET_KEY=$(uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  python3 -c "
import re
path = '.env'
key = '''${SECRET_KEY}'''
text = open(path).read()
text = re.sub(r'^ARGUS_SECRET_KEY=.*$', f'ARGUS_SECRET_KEY={key}', text, flags=re.M)
open(path, 'w').write(text)
"
fi

echo "Applying database migrations..."
uv run alembic upgrade head

echo
echo "✓ Argus Agent ${VERSION} installed at ${INSTALL_DIR}"
echo
echo "To run it:"
echo "  cd ${INSTALL_DIR} && uv run argus          # API + UI at http://127.0.0.1:8765"
echo "  cd ${INSTALL_DIR} && uv run argus-worker   # processes runs (separate terminal)"
echo
echo "'web' runs already work with the setup above. For Android/iOS (Android Studio,"
echo "Xcode, Appium), run: cd ${INSTALL_DIR} && ./scripts/bootstrap.sh"
echo
echo "Want it to start on login? cd ${INSTALL_DIR} && ./scripts/launchd/install.sh"
echo
echo "Run this script again any time to update — ~/.argus/ (database, artifacts, .env) is never touched."
