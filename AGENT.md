# Qwen Dictation Agent Notes

This is a local macOS dictation MVP using Qwen3-ASR 1.7B.

## Product rules

- Keep one live-streaming input flow: hold-to-talk and toggle start/stop.
- Keep the menu-bar app and local dashboard at `http://127.0.0.1:5001`.
- Treat approved vocabulary as Qwen context hints, never guaranteed replacement.
- Store only the latest 50 final transcript texts locally. Never track edits in
  external apps or silently learn vocabulary.

## Runtime and testing

- Run with `./venv/bin/python whisper-dictation.py`.
- Prefer Apple Silicon MPS; CPU fallback is allowed.
- Before claiming the app works, run Python compile checks, `pytest`, the
  design.md lint, and a packaged app build when packaging changes are touched.
- After implementing or changing a feature, verify it directly before reporting
  completion. Prefer an executable check over reasoning from code.
- When UI is changed, launch the relevant screen and capture screenshots before
  completion. Inspect the screenshots for broken spacing, overlapping text or
  controls, clipped labels, awkward empty space, and desktop/mobile responsive
  issues where applicable.
- For dashboard changes, verify against `http://127.0.0.1:5001` with a real
  browser screenshot. For macOS app windows or HUD changes, capture the relevant
  local window/state and check the visual result before claiming it is done.
- Keep microphone and Accessibility permission notes current.

## Editing rules

- Keep the app small and local-first. Do not add paid cloud STT APIs.
- Do not reintroduce Whisper, batch, review-card, or find-replace paths.
- Preserve user files under `~/.qwen-dictation/`.
