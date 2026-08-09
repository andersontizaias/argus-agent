#!/usr/bin/env bash
# Argus Agent — empacota o ArgusAgentInstaller.pkg (ver build-pkg.sh) num
# .dmg pra distribuição. Precisa rodar build-pkg.sh antes.
#
# Uso: packaging/macos/build-dmg.sh
# Saída: packaging/macos/build/ArgusAgent-Installer.dmg
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Error: hdiutil is macOS-only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"
PKG_PATH="${BUILD_DIR}/ArgusAgentInstaller.pkg"
DMG_PATH="${BUILD_DIR}/ArgusAgent-Installer.dmg"

if [[ ! -f "${PKG_PATH}" ]]; then
  echo "Error: ${PKG_PATH} not found — run build-pkg.sh first." >&2
  exit 1
fi

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf "${STAGING_DIR}"' EXIT
cp "${PKG_PATH}" "${STAGING_DIR}/"
cp "${SCRIPT_DIR}/resources/welcome.txt" "${STAGING_DIR}/Read Me.txt"

rm -f "${DMG_PATH}"
hdiutil create \
  -volname "Argus Agent Installer" \
  -srcfolder "${STAGING_DIR}" \
  -ov -format UDZO \
  "${DMG_PATH}"

echo
echo "✓ ${DMG_PATH}"
