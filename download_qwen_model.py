import argparse
import os
import subprocess
from pathlib import Path


MODEL_URL = "https://hf-mirror.com/Qwen/Qwen3-ASR-0.6B/resolve/main/model.safetensors"
MODEL_SIZE = 1876091704


def download_parts(output_dir, parts):
    output_dir.mkdir(parents=True, exist_ok=True)
    chunk = (MODEL_SIZE + parts - 1) // parts
    procs = []
    for idx in range(parts):
        start = idx * chunk
        end = min(MODEL_SIZE - 1, (idx + 1) * chunk - 1)
        part_path = output_dir / f"part-{idx}"
        log_path = output_dir / f"part-{idx}.log"
        cmd = [
            "curl",
            "-L",
            "--fail",
            "--retry",
            "5",
            "--retry-delay",
            "2",
            "--connect-timeout",
            "20",
            "-r",
            f"{start}-{end}",
            "-o",
            str(part_path),
            MODEL_URL,
        ]
        log = open(log_path, "wb")
        procs.append((subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT), log))
    failed = 0
    for proc, log in procs:
        failed += proc.wait() != 0
        log.close()
    if failed:
        raise SystemExit(f"{failed} download workers failed")


def combine_parts(output_dir, final_path, parts):
    with open(final_path, "wb") as out:
        for idx in range(parts):
            part_path = output_dir / f"part-{idx}"
            with open(part_path, "rb") as part:
                while True:
                    chunk = part.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
    size = final_path.stat().st_size
    if size != MODEL_SIZE:
        raise SystemExit(f"unexpected model size: {size} != {MODEL_SIZE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts-dir", default="/tmp/qwen3-asr-0.6b-parts")
    parser.add_argument("--output", default="/tmp/qwen3-asr-0.6b-model.safetensors")
    parser.add_argument("--parts", type=int, default=8)
    parser.add_argument("--combine-only", action="store_true")
    args = parser.parse_args()

    parts_dir = Path(args.parts_dir)
    output = Path(args.output)
    if not args.combine_only:
        download_parts(parts_dir, args.parts)
    combine_parts(parts_dir, output, args.parts)
    print(output)


if __name__ == "__main__":
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    main()
