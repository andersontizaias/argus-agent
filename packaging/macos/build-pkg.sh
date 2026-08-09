#!/usr/bin/env bash
# Argus Agent — builda o instalador .pkg (wizard visual, sem payload). O
# pacote não carrega o código da app: o postinstall baixa a release mais
# recente via scripts/install.sh (mesmo caminho de uma instalação manual) —
# então este pacote não precisa ser rebuildado a cada release do app, só
# quando a lógica do próprio wizard mudar. Rode de novo (com um "version"
# maior) só quando editar algo em packaging/macos/.
#
# Uso: packaging/macos/build-pkg.sh [versão-do-wizard]
# Saída: packaging/macos/build/ArgusAgentInstaller.pkg
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Error: pkgbuild/productbuild are macOS-only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIZARD_VERSION="${1:-1.0}"
BUILD_DIR="${SCRIPT_DIR}/build"

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

echo "== Building the component package (--nopayload) =="
pkgbuild \
  --nopayload \
  --scripts "${SCRIPT_DIR}/scripts" \
  --identifier com.andersontizaias.argus-agent.installer \
  --version "${WIZARD_VERSION}" \
  "${BUILD_DIR}/component.pkg"

echo "== Building the distribution (wizard UI) package =="
DIST_XML="${BUILD_DIR}/distribution.xml"
sed "s/__WIZARD_VERSION__/${WIZARD_VERSION}/" "${SCRIPT_DIR}/distribution.xml" > "${DIST_XML}"

productbuild \
  --distribution "${DIST_XML}" \
  --resources "${SCRIPT_DIR}/resources" \
  --package-path "${BUILD_DIR}" \
  "${BUILD_DIR}/ArgusAgentInstaller.pkg"

echo
echo "✓ ${BUILD_DIR}/ArgusAgentInstaller.pkg"
echo
echo "Not signed/notarized (no paid Apple Developer account) — Gatekeeper may"
echo "warn on first open. Downloading via curl/gh (not a browser) avoids the"
echo "quarantine flag that triggers that warning in the first place."
