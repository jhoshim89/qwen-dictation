#!/bin/bash
# Optional local Korean sherpa-onnx Zipformer runtime.
set -e
cd "$(dirname "$0")"

MODEL_ID="${SHERPA_ONNX_KO_MODEL:-k2-fsa/sherpa-onnx-streaming-zipformer-korean-2024-06-16}"
MODEL_DIR="${SHERPA_ONNX_KO_MODEL_PATH:-$HOME/.qwen-dictation/models/sherpa-onnx-streaming-zipformer-korean-2024-06-16}"

./venv/bin/python -m pip install 'sherpa-onnx>=1.13,<2'

HF_HUB_DISABLE_XET=1 HF_HUB_ENABLE_HF_TRANSFER=1 ./venv/bin/python - <<PY
from huggingface_hub import snapshot_download

model_id = "${MODEL_ID}"
model_dir = "${MODEL_DIR}"
path = snapshot_download(repo_id=model_id, local_dir=model_dir)
print(f"sherpa-onnx Korean model ready: {path}")
PY
