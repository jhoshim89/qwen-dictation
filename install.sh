#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${QWEN_DICTATION_REPO:-https://github.com/jhoshim89/qwen-dictation.git}"
BRANCH="${QWEN_DICTATION_BRANCH:-feat/bottom-overlay}"
INSTALL_DIR="${QWEN_DICTATION_INSTALL_DIR:-$HOME/.qwen-dictation/source}"
MODEL_ID="${QWEN_DICTATION_MODEL:-Qwen/Qwen3-ASR-1.7B}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Qwen Dictation currently supports macOS only."
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "==> Installing Homebrew"
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required. Install Xcode Command Line Tools first:"
  echo "xcode-select --install"
  exit 1
fi

echo "==> Installing PortAudio"
brew list portaudio >/dev/null 2>&1 || brew install portaudio

echo "==> Installing Qwen Dictation into $INSTALL_DIR"
if [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" fetch origin "$BRANCH"
  git -C "$INSTALL_DIR" checkout "$BRANCH"
  git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

echo "==> Creating Python environment"
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "==> Downloading speech model: $MODEL_ID"
HF_HUB_DISABLE_XET=1 HF_HUB_ENABLE_HF_TRANSFER=1 python - <<PY
from huggingface_hub import snapshot_download

model_id = "${MODEL_ID}"
path = snapshot_download(repo_id=model_id)
print(f"Model ready: {path}")
PY

echo "==> Launching Qwen Dictation"
echo "Grant Microphone and Accessibility permissions when macOS asks."
exec ./run.sh
