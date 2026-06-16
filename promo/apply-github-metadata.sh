#!/usr/bin/env bash
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is not installed. Install it first: https://cli.github.com/"
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI auth is not valid. Run: gh auth login -h github.com"
  exit 1
fi

gh repo edit jhoshim89/qwen-dictation \
  --description "Local-first macOS dictation powered by Qwen3-ASR. Hold Right Ctrl, speak, and type into any app." \
  --homepage "https://jhoshim89.github.io/qwen-dictation/" \
  --add-topic macos \
  --add-topic dictation \
  --add-topic speech-to-text \
  --add-topic asr \
  --add-topic qwen \
  --add-topic local-ai \
  --add-topic privacy \
  --add-topic accessibility \
  --add-topic mlx \
  --add-topic productivity

echo "GitHub repository metadata updated."
