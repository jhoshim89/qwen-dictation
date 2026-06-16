import argparse
import csv
import importlib.util
import statistics
import time
from pathlib import Path

import torch

import app_config
import asr_engines
import vocabulary


AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aiff", ".aif"}


def _load_app_module():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def levenshtein(a, b):
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (ca != cb)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def normalize_chars(text):
    return "".join(str(text or "").split())


def cer(reference, hypothesis):
    ref = normalize_chars(reference)
    hyp = normalize_chars(hypothesis)
    if not ref:
        return None
    return levenshtein(ref, hyp) / len(ref)


def wer(reference, hypothesis):
    ref = str(reference or "").split()
    hyp = str(hypothesis or "").split()
    if not ref:
        return None
    return levenshtein(ref, hyp) / len(ref)


def audio_items(audio_dir, limit=None):
    root = Path(audio_dir)
    paths = sorted(p for p in root.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES)
    if limit:
        paths = paths[:limit]
    for path in paths:
        ref_path = path.with_suffix(".txt")
        reference = ref_path.read_text(encoding="utf-8").strip() if ref_path.exists() else ""
        yield path, reference


def context_for_mode(mode):
    if mode == "app":
        cfg = app_config.load_config()
        return vocabulary.build_context(vocabulary.load_vocabulary(), cfg.get("domain_context", ""))
    return ""


def transcribe_one(transcriber, engine, audio_path, language, context):
    transcriber.set_engine(engine)
    started = time.perf_counter()
    text = transcriber.transcribe_file(
        str(audio_path),
        language=language,
        context=context if asr_engines.asr_engine_supports_context(engine) else "",
    )
    return text, time.perf_counter() - started


def summarize(rows, engines):
    lines = []
    scored = [r for r in rows if r["cer"] != ""]
    for engine in engines:
        subset = [r for r in scored if r["engine"] == engine]
        timed = [r for r in rows if r["engine"] == engine]
        mean_cer = statistics.fmean(float(r["cer"]) for r in subset) if subset else None
        mean_wer = statistics.fmean(float(r["wer"]) for r in subset) if subset else None
        median_sec = statistics.median(float(r["seconds"]) for r in timed) if timed else None
        lines.append({
            "engine": engine,
            "label": asr_engines.asr_engine_label(engine),
            "mean_cer": mean_cer,
            "mean_wer": mean_wer,
            "median_sec": median_sec,
            "n": len(timed),
            "scored_n": len(subset),
        })
    return lines


def recommendation(summary):
    scored = [s for s in summary if s["mean_cer"] is not None]
    if not scored:
        return "정답 .txt가 없어 정확도 추천은 보류합니다. CSV의 seconds와 raw text를 직접 확인하세요."
    best_cer = min(s["mean_cer"] for s in scored)
    close = [s for s in scored if s["mean_cer"] <= best_cer * 1.05 + 0.002]
    winner = min(close, key=lambda s: s["median_sec"] if s["median_sec"] is not None else float("inf"))
    return (
        f"추천: {winner['label']} "
        f"(mean CER {winner['mean_cer']:.3f}, median {winner['median_sec']:.2f}s)."
    )


def main():
    parser = argparse.ArgumentParser(description="Compare selectable ASR engines on the same local audio set.")
    parser.add_argument("audio_dir", help="Folder with audio files and optional same-stem .txt references.")
    parser.add_argument("--engines", default="qwen,nemotron_mlx", help="Comma-separated engine ids.")
    parser.add_argument("--language", default="ko", help="App language code, e.g. ko, en, auto.")
    parser.add_argument("--context", choices=["none", "app"], default="none")
    parser.add_argument("--output", default="asr_compare.csv")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-preload", action="store_true", help="Include cold model load in the first file timing.")
    args = parser.parse_args()

    engines = [asr_engines.normalize_asr_engine(e) for e in args.engines.split(",") if e.strip()]
    if not engines:
        raise SystemExit("No engines selected.")

    wd = _load_app_module()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device == "mps" else torch.float32
    transcriber = wd.SpeechTranscriber(device, dtype)
    transcriber.min_volume = 1
    context = context_for_mode(args.context)
    items = list(audio_items(args.audio_dir, limit=args.limit or None))

    if not args.no_preload:
        for engine in engines:
            transcriber.set_engine(engine)
            started = time.perf_counter()
            transcriber.preload_current_model()
            print(f"preloaded {engine} in {time.perf_counter() - started:.2f}s")
            if items:
                _, warm_seconds = transcribe_one(
                    transcriber,
                    engine,
                    items[0][0],
                    args.language,
                    context,
                )
                print(f"warmed {engine} transcription path in {warm_seconds:.2f}s")

    rows = []
    for audio_path, reference in items:
        for engine in engines:
            text, seconds = transcribe_one(transcriber, engine, audio_path, args.language, context)
            row_cer = cer(reference, text)
            row_wer = wer(reference, text)
            rows.append({
                "file": audio_path.name,
                "engine": engine,
                "engine_label": asr_engines.asr_engine_label(engine),
                "language": args.language,
                "seconds": f"{seconds:.4f}",
                "cer": "" if row_cer is None else f"{row_cer:.6f}",
                "wer": "" if row_wer is None else f"{row_wer:.6f}",
                "reference": reference,
                "text": text,
            })
            print(f"{audio_path.name} [{engine}] {seconds:.2f}s: {text}")

    if not rows:
        raise SystemExit(f"No audio files found in {args.audio_dir}")

    output = Path(args.output)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = summarize(rows, engines)
    print()
    for item in summary:
        cer_text = "-" if item["mean_cer"] is None else f"{item['mean_cer']:.3f}"
        wer_text = "-" if item["mean_wer"] is None else f"{item['mean_wer']:.3f}"
        sec_text = "-" if item["median_sec"] is None else f"{item['median_sec']:.2f}s"
        print(f"{item['label']}: n={item['n']} scored={item['scored_n']} mean CER={cer_text} mean WER={wer_text} median={sec_text}")
    print(recommendation(summary))
    print(f"CSV: {output.resolve()}")


if __name__ == "__main__":
    main()
