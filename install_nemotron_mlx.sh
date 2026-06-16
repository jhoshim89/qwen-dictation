#!/bin/bash
# Optional Nemotron 3.5 ASR MLX runtime.
#
# mlx-audio 0.4.4 declares transformers>=5 in package metadata, while qwen-asr
# currently requires transformers==4.57.6. Install the package without its
# resolver dependencies so Qwen stays usable in the same venv.
set -e
cd "$(dirname "$0")"

./venv/bin/python -m pip install 'mlx>=0.31.1' miniaudio sentencepiece protobuf
./venv/bin/python -m pip install --no-deps 'mlx-audio==0.4.4'
./venv/bin/python -m pip install --no-deps 'mlx-lm==0.31.3'
HF_HUB_DISABLE_XET=1 HF_HUB_ENABLE_HF_TRANSFER=0 ./venv/bin/python download_qwen_model.py --engine nemotron_mlx
