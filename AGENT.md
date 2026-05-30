# Qwen Dictation Agent Notes

This project is a local macOS dictation MVP using Qwen3-ASR. Keep the app free and local-first.

## Product Goal

- Use local Qwen3-ASR models for STT. Do not add paid cloud STT APIs unless the user explicitly asks.
- Support three MVP input modes:
  - `streaming`: repeatedly transcribe while recording and type the visible diff into the focused field.
  - `batch_paste`: record first, transcribe once, paste into the focused field.
  - `batch_submit`: record first, transcribe once, paste into the focused field, then press Return.
- Keep the macOS menu bar app and the local dashboard at `http://127.0.0.1:5001`.

## Runtime Rules

- Run with the project virtualenv: `./venv/bin/python whisper-dictation.py`.
- Prefer Apple Silicon MPS when available. CPU fallback is allowed but slower.
- Keep microphone, Accessibility, and Automation permission notes current in `README.md`.
- Never commit model weights, `venv/`, caches, or generated `__pycache__/` files.

## Testing Rules

- Before claiming the app works, run at least:
  - Python compile/import checks.
  - Dashboard API checks.
  - A Qwen transcription check using a local audio file.
  - A paste/Return pipeline check in a controlled prompt field.
- If macOS blocks input automation, report the exact permission that must be enabled instead of calling the app broken.

## Editing Rules

- Keep the app small and MVP-focused.
- Do not reintroduce Whisper dependency paths unless explicitly requested.
- Treat `dictionary.json` as user-editable data. Avoid replacing the user's entries.
