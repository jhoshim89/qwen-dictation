#!/bin/bash
# Optional Apple Silicon MLX runtime shared by the "Qwen3-ASR 1.7B (MLX)" and
# "Nemotron 3.5 ASR 0.6B (MLX)" dashboard engines.
#
# mlx-audio 0.4.4 declares transformers>=5 in package metadata, while qwen-asr
# currently requires transformers==4.57.6. Install the package without its
# resolver dependencies so the default torch Qwen engine stays usable in the
# same venv.
#
# Usage:
#   ./install_mlx_runtime.sh            # runtime + Qwen3-ASR 1.7B MLX 8bit weights
#   ./install_mlx_runtime.sh nemotron   # runtime + Nemotron weights
#   ./install_mlx_runtime.sh all        # runtime + both
set -e
cd "$(dirname "$0")"

WHICH="${1:-qwen}"

./venv/bin/python -m pip install 'mlx>=0.31.1' miniaudio sentencepiece protobuf
./venv/bin/python -m pip install --no-deps 'mlx-audio==0.4.4'
./venv/bin/python -m pip install --no-deps 'mlx-lm==0.31.3'

if [ "$WHICH" = "qwen" ] || [ "$WHICH" = "all" ]; then
  HF_HUB_DISABLE_XET=1 HF_HUB_ENABLE_HF_TRANSFER=0 ./venv/bin/python download_qwen_model.py --engine qwen_mlx
fi
if [ "$WHICH" = "nemotron" ] || [ "$WHICH" = "all" ]; then
  HF_HUB_DISABLE_XET=1 HF_HUB_ENABLE_HF_TRANSFER=0 ./venv/bin/python download_qwen_model.py --engine nemotron_mlx
fi
