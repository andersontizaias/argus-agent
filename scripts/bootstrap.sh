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
  echo "Erro: bootstrap.sh é específico do macOS." >&2
  exit 1
fi

if [[ ! -f "${ROOT_DIR}/pyproject.toml" ]]; then
  echo "Erro: ${ROOT_DIR} não parece o checkout do Argus Agent (sem pyproject.toml)." >&2
  exit 1
fi

# 1. Homebrew + uv + Node 22 ------------------------------------------------
_step "Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  _warn "não encontrado — instalando..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
else
  _ok "já instalado ($(brew --version | head -1))"
fi

_step "uv"
if ! command -v uv >/dev/null 2>&1; then
  brew install uv
else
  _ok "já instalado ($(uv --version))"
fi

_step "Node.js 22"
if command -v node >/dev/null 2>&1 && [[ "$(node -v)" == v22* ]]; then
  _ok "já instalado ($(node -v))"
else
  brew install node@22
  # node@22 é keg-only no Homebrew (não symlinka /opt/homebrew/bin/node pra
  # não brigar com outra versão que o dev já use noutros projetos) — só
  # ajusta o PATH desta sessão do script, pro build do frontend abaixo.
  NODE22_BIN="$(brew --prefix node@22)/bin"
  export PATH="${NODE22_BIN}:${PATH}"
  _ok "instalado via Homebrew — para usar fora deste script, adicione ${NODE22_BIN} ao seu PATH"
fi

# 2. Android -----------------------------------------------------------------
_step "Android SDK"
ANDROID_HOME_DIR="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-${HOME}/Library/Android/sdk}}"
if [[ ! -d "${ANDROID_HOME_DIR}" ]]; then
  _warn "SDK não encontrado em ${ANDROID_HOME_DIR}."
  cat <<EOF
    Instale o Android Studio (https://developer.android.com/studio), abra-o
    uma vez pra ele baixar o SDK padrão, e crie um AVD chamado
    '${ARGUS_ANDROID_AVD:-Pixel_9a}' pelo Device Manager (qualquer imagem
    de sistema recente arm64 serve). Rode este script de novo depois.
EOF
else
  _ok "SDK em ${ANDROID_HOME_DIR}"
  AVD_NAME="${ARGUS_ANDROID_AVD:-Pixel_9a}"
  EMULATOR_BIN="${ANDROID_HOME_DIR}/emulator/emulator"
  if [[ -x "${EMULATOR_BIN}" ]] && "${EMULATOR_BIN}" -list-avds 2>/dev/null | grep -qx "${AVD_NAME}"; then
    _ok "AVD '${AVD_NAME}' já existe"
  else
    _warn "AVD '${AVD_NAME}' não encontrado."
    echo "    Crie pelo Device Manager do Android Studio com esse nome exato —"
    echo "    baixa uma imagem de sistema (~1-2 GB), por isso o script não faz sozinho."
  fi
fi

# 3. iOS -----------------------------------------------------------------
_step "iOS (Xcode/simulador)"
if ! command -v xcrun >/dev/null 2>&1; then
  _warn "Xcode Command Line Tools não encontrado — instale o Xcode pela App Store."
else
  if xcrun simctl list runtimes 2>/dev/null | grep -qi "iOS"; then
    _ok "runtime iOS instalado"
  else
    _warn "nenhum runtime iOS instalado."
    echo "    Rode manualmente: xcodebuild -downloadPlatform iOS  (baixa alguns GB)"
  fi
  IOS_DEVICE_NAME="${ARGUS_IOS_DEVICE:-iPhone 15}"
  if xcrun simctl list devices 2>/dev/null | grep -q "${IOS_DEVICE_NAME} ("; then
    _ok "simulador '${IOS_DEVICE_NAME}' já existe"
  else
    _warn "simulador '${IOS_DEVICE_NAME}' não encontrado — crie pelo Xcode (Window > Devices and Simulators)."
  fi
fi

# 4. Appium -----------------------------------------------------------------
_step "Appium"
if ! command -v appium >/dev/null 2>&1; then
  npm install -g appium
else
  _ok "já instalado ($(appium --version))"
fi
INSTALLED_DRIVERS="$(appium driver list --installed 2>/dev/null || true)"
for driver in uiautomator2 xcuitest; do
  if grep -q "${driver}" <<<"${INSTALLED_DRIVERS}"; then
    _ok "driver ${driver} já instalado"
  else
    appium driver install "${driver}"
  fi
done
appium driver doctor uiautomator2 || _warn "appium driver doctor uiautomator2 encontrou pendências (acima)"
appium driver doctor xcuitest || _warn "appium driver doctor xcuitest encontrou pendências (acima)"

# 5. Backend Python -----------------------------------------------------------------
_step "Backend (uv sync + Playwright + .env + migrações)"
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
  _ok ".env criado com ARGUS_SECRET_KEY nova"
else
  _ok ".env já existe (preservado)"
fi
uv run alembic upgrade head

# 6. Frontend -----------------------------------------------------------------
_step "Frontend (npm ci + build)"
if [[ -f frontend/package.json ]]; then
  (cd frontend && npm ci && npm run build)
else
  # Checkout instalado a partir do tarball de release (scripts/install.sh):
  # só o frontend/dist já compilado vem no pacote, sem frontend/package.json.
  _ok "frontend/dist já vem pronto na release — nada a compilar"
fi

# 7. Resumo final -----------------------------------------------------------------
_step "argus-doctor"
if uv run argus-doctor; then
  echo
  echo "Pronto — tudo verde. Rode 'uv run argus' e 'uv run argus-worker' (ou"
  echo "scripts/launchd/install.sh pra subir sozinho no login)."
else
  echo
  _warn "algumas checagens acima falharam — normal se Android/iOS ainda não"
  _warn "foram configurados (veja os avisos desta execução). Web funciona já."
fi
