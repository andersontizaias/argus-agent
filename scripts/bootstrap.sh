#!/usr/bin/env bash
# Argus Agent — bootstrap nativo idempotente (macOS). Deixa a máquina pronta
# pra rodar `argus`/`argus-worker` localmente: Homebrew, uv, Node, backend
# Python, frontend, banco.
#
# Android/iOS dependem de instalações pesadas (Android Studio, Xcode) e de
# baixar GBs de imagem de sistema/runtime — este script CHECA e INSTRUI,
# nunca baixa isso sozinho (mesmo espírito do "não baixa GB sem confirmar"
# do resto do projeto).
#
# Idempotente: rodar de novo só corrige o que falta, sem reinstalar o que já
# está ok. Termina rodando `argus-doctor` como resumo final — plataformas
# mobile não configuradas aparecem com "✗" ali, não travam o script.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

_step() { echo; echo "== $* =="; }
_ok() { echo "  ✓ $*"; }
_warn() { echo "  ⚠ $*" >&2; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Error: bootstrap.sh is macOS-only." >&2
  exit 1
fi

if [[ ! -f "${ROOT_DIR}/pyproject.toml" ]]; then
  echo "Error: ${ROOT_DIR} doesn't look like the Argus Agent checkout (no pyproject.toml)." >&2
  exit 1
fi

# 1. Homebrew + uv + Node 22 ------------------------------------------------
_step "Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  _warn "not found — installing..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
else
  _ok "already installed ($(brew --version | head -1))"
fi

_step "uv"
if ! command -v uv >/dev/null 2>&1; then
  brew install uv
else
  _ok "already installed ($(uv --version))"
fi

_step "Node.js 22"
if command -v node >/dev/null 2>&1 && [[ "$(node -v)" == v22* ]]; then
  _ok "already installed ($(node -v))"
else
  brew install node@22
  # node@22 é keg-only no Homebrew (não symlinka /opt/homebrew/bin/node pra
  # não brigar com outra versão que o dev já use noutros projetos) — só
  # ajusta o PATH desta sessão do script, pro build do frontend abaixo.
  NODE22_BIN="$(brew --prefix node@22)/bin"
  export PATH="${NODE22_BIN}:${PATH}"
  _ok "installed via Homebrew — to use it outside this script, add ${NODE22_BIN} to your PATH"
fi

# 2. Android -----------------------------------------------------------------
_step "Android SDK"
ANDROID_HOME_DIR="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-${HOME}/Library/Android/sdk}}"
if [[ ! -d "${ANDROID_HOME_DIR}" ]]; then
  _warn "SDK not found at ${ANDROID_HOME_DIR}."
  cat <<EOF
    Install Android Studio (https://developer.android.com/studio), open it
    once so it downloads the default SDK, and create an AVD named
    '${ARGUS_ANDROID_AVD:-Pixel_9a}' via the Device Manager (any recent
    arm64 system image works). Run this script again afterwards.
EOF
else
  _ok "SDK at ${ANDROID_HOME_DIR}"
  # Exportado pro resto do script (Appium doctor logo abaixo, e qualquer
  # `npm`/`appium` chamado depois) — sem isso, ANDROID_HOME/JAVA_HOME só
  # existem dentro do processo Python do Argus (efeito colateral de
  # src/android_env.py), nunca no shell que roda este script.
  export ANDROID_HOME="${ANDROID_HOME_DIR}"
  export ANDROID_SDK_ROOT="${ANDROID_HOME_DIR}"
  if [[ -z "${JAVA_HOME:-}" ]]; then
    ANDROID_STUDIO_JBR="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
    [[ -d "${ANDROID_STUDIO_JBR}" ]] && export JAVA_HOME="${ANDROID_STUDIO_JBR}"
  fi
  AVD_NAME="${ARGUS_ANDROID_AVD:-Pixel_9a}"
  EMULATOR_BIN="${ANDROID_HOME_DIR}/emulator/emulator"
  if [[ -x "${EMULATOR_BIN}" ]] && "${EMULATOR_BIN}" -list-avds 2>/dev/null | grep -qx "${AVD_NAME}"; then
    _ok "AVD '${AVD_NAME}' already exists"
  else
    _warn "AVD '${AVD_NAME}' not found."
    echo "    Create it via the Android Studio Device Manager with that exact name —"
    echo "    it downloads a system image (~1-2 GB), so this script doesn't do it on its own."
  fi
fi

# 3. iOS -----------------------------------------------------------------
_step "iOS (Xcode/simulator)"
if ! command -v xcrun >/dev/null 2>&1; then
  _warn "Xcode Command Line Tools not found — install Xcode from the App Store."
else
  if xcrun simctl list runtimes 2>/dev/null | grep -qi "iOS"; then
    _ok "iOS runtime installed"
  else
    _warn "no iOS runtime installed."
    echo "    Run manually: xcodebuild -downloadPlatform iOS  (downloads a few GB)"
  fi
  IOS_DEVICE_NAME="${ARGUS_IOS_DEVICE:-iPhone 15}"
  if xcrun simctl list devices 2>/dev/null | grep -q "${IOS_DEVICE_NAME} ("; then
    _ok "simulator '${IOS_DEVICE_NAME}' already exists"
  else
    _warn "simulator '${IOS_DEVICE_NAME}' not found — create it via Xcode (Window > Devices and Simulators)."
  fi
fi

# 4. Appium -----------------------------------------------------------------
_step "Appium"
if ! command -v appium >/dev/null 2>&1; then
  npm install -g appium
else
  _ok "already installed ($(appium --version))"
fi
# appium escreve a lista em stderr, não stdout (confirmado ao vivo) — 2>&1
# é necessário, só stdout deixava INSTALLED_DRIVERS sempre vazio e o script
# tentava reinstalar um driver já presente, o que o appium recusa.
INSTALLED_DRIVERS="$(appium driver list --installed 2>&1 || true)"
for driver in uiautomator2 xcuitest; do
  if grep -q "${driver}" <<<"${INSTALLED_DRIVERS}"; then
    _ok "driver ${driver} already installed"
  else
    appium driver install "${driver}"
  fi
done
appium driver doctor uiautomator2 || _warn "appium driver doctor uiautomator2 found issues (above)"
appium driver doctor xcuitest || _warn "appium driver doctor xcuitest found issues (above)"

# 5. Backend Python -----------------------------------------------------------------
_step "Backend (uv sync + Playwright + .env + migrations)"
uv sync
uv run playwright install chromium
if [[ ! -f .env ]]; then
  cp .env.example .env
  SECRET_KEY="$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  python3 -c "
import re
path = '.env'
key = '''${SECRET_KEY}'''
text = open(path).read()
text = re.sub(r'^ARGUS_SECRET_KEY=.*$', f'ARGUS_SECRET_KEY={key}', text, flags=re.M)
open(path, 'w').write(text)
"
  _ok ".env created with a new ARGUS_SECRET_KEY"
else
  _ok ".env already exists (preserved)"
fi
uv run alembic upgrade head

# 6. Frontend -----------------------------------------------------------------
_step "Frontend (npm ci + build)"
if [[ -f frontend/package.json ]]; then
  (cd frontend && npm ci && npm run build)
else
  # Checkout instalado a partir do tarball de release (scripts/install.sh):
  # só o frontend/dist já compilado vem no pacote, sem frontend/package.json.
  _ok "frontend/dist already comes prebuilt in the release — nothing to build"
fi

# 7. Resumo final -----------------------------------------------------------------
_step "argus-doctor"
if uv run argus-doctor; then
  echo
  echo "Done — all green. Run 'uv run argus' and 'uv run argus-worker' (or"
  echo "scripts/launchd/install.sh to start them automatically on login)."
else
  echo
  _warn "some checks above failed — normal if Android/iOS haven't been"
  _warn "set up yet (see the warnings from this run). Web already works."
fi
