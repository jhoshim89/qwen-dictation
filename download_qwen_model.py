import argparse
import os

from huggingface_hub import snapshot_download


DEFAULT_MODEL = "Qwen/Qwen3-ASR-1.7B"


def main():
    parser = argparse.ArgumentParser(description="Download the Qwen Dictation ASR model.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

    path = snapshot_download(repo_id=args.model)
    print(path)


if __name__ == "__main__":
    main()
