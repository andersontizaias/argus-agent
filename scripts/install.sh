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

echo "== Argus Agent — instalador =="
echo "Destino: $INSTALL_DIR"
echo

for bin in curl python3; do
  command -v "$bin" >/dev/null 2>&1 || { echo "Erro: '$bin' não encontrado no PATH." >&2; exit 1; }
done
if ! command -v uv >/dev/null 2>&1; then
  echo "Erro: 'uv' não encontrado. Instale antes: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
  read -rsp "GitHub token (repo privado, escopo 'repo' clássico — não 'read:packages', que é só pro GitHub Packages, nem fine-grained): " GITHUB_TOKEN
  echo
fi
export GITHUB_TOKEN

TMP_TARBALL=""
RELEASE_JSON_FILE="$(mktemp -t argus-release-XXXXXX).json"
trap 'rm -f "${RELEASE_JSON_FILE}" "${TMP_TARBALL}"' EXIT

echo "Buscando a release mais recente..."
curl -sf \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -o "${RELEASE_JSON_FILE}" \
  "https://api.github.com/repos/${REPO}/releases/latest" \
  || { echo "Erro: não consegui consultar a release (token inválido ou sem acesso ao repo?)." >&2; exit 1; }

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
  echo "Erro: não encontrei o tarball na release ${VERSION:-desconhecida}." >&2
  exit 1
fi
echo "Versão encontrada: ${VERSION}"

TMP_TARBALL="$(mktemp -t argus-agent-XXXXXX).tar.gz"
echo "Baixando..."
curl -sfL \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H "Accept: application/octet-stream" \
  -o "${TMP_TARBALL}" \
  "${ASSET_URL}"

mkdir -p "${INSTALL_DIR}"
echo "Extraindo em ${INSTALL_DIR}..."
tar -xzf "${TMP_TARBALL}" -C "${INSTALL_DIR}" --strip-components=1
rm -f "${TMP_TARBALL}"

cd "${INSTALL_DIR}"

echo "Instalando dependências Python (uv sync)..."
uv sync

echo "Instalando o Chromium do Playwright..."
uv run playwright install chromium

if [ ! -f .env ]; then
  echo "Gerando .env com uma ARGUS_SECRET_KEY nova..."
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

echo "Aplicando migrações do banco..."
uv run alembic upgrade head

echo
echo "✓ Argus Agent ${VERSION} instalado em ${INSTALL_DIR}"
echo
echo "Para rodar:"
echo "  cd ${INSTALL_DIR} && uv run argus          # API + UI em http://127.0.0.1:8765"
echo "  cd ${INSTALL_DIR} && uv run argus-worker   # processa as execuções (em outro terminal)"
echo
echo "Runs 'web' já funcionam com o setup acima. Para Android/iOS (Android Studio,"
echo "Xcode, Appium), rode: cd ${INSTALL_DIR} && ./scripts/bootstrap.sh"
echo
echo "Sobe sozinho no login? cd ${INSTALL_DIR} && ./scripts/launchd/install.sh"
echo
echo "Rode este script de novo a qualquer momento para atualizar — ~/.argus/ (banco, artefatos, .env) nunca é tocado."
