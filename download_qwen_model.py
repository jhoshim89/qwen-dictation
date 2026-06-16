import argparse
import os

from huggingface_hub import snapshot_download

import asr_engines

DEFAULT_MODEL = asr_engines.QWEN_MODEL_ID


def main():
    parser = argparse.ArgumentParser(description="Download an ASR model used by Qwen Dictation.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--engine",
        choices=[asr_engines.ASR_ENGINE_QWEN, asr_engines.ASR_ENGINE_NEMOTRON_MLX],
        help="Download the configured default model for this engine.",
    )
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault(
        "HF_HUB_ENABLE_HF_TRANSFER",
        "0" if args.engine == asr_engines.ASR_ENGINE_NEMOTRON_MLX else "1",
    )

    model = asr_engines.asr_engine_model(args.engine) if args.engine else args.model
    path = snapshot_download(repo_id=model)
    print(path)


if __name__ == "__main__":
    main()
