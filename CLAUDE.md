# CLAUDE.md

## What this is

Qwen Dictation is a local-first macOS menu-bar dictation app powered by
switchable local ASR engines. **Qwen3-ASR 1.7B** is the default; **Qwen
Original** and **Nemotron 3.5 ASR 0.6B (MLX)** can be selected for comparison/use.
It records microphone audio, transcribes locally, and types the visible diff
into the focused input field. The Flask dashboard at
`http://127.0.0.1:5001` edits live settings and user vocabulary.

The historical entry point remains `whisper-dictation.py`. Do not reintroduce
Whisper, batch paste, review cards, string replacement dictionaries, or paid
cloud STT paths unless explicitly requested.

## Run and verify

```bash
./run.sh
./venv/bin/python -m py_compile whisper-dictation.py dashboard.py dictation_history.py hud_overlay.py
./venv/bin/pytest -q
```

Optional CLI flags are `-l/--language` and `-t/--max_time`. The dashboard is the
normal place to configure language, microphone, max recording time, and the two
hotkeys.

## Architecture

- `StatusBarApp` owns menu-bar state, hotkey rebinding, the recorder, and the
  in-process AppKit HUD timer.
- `MultiHotkeyListener` is the only listener. The hold key dictates while
  pressed; the toggle key starts and stops a session. Both use the same live
  streaming path.
- `Recorder._stream_loop` wakes every `STREAM_INTERVAL` (0.8s), transcribes the
  current audio window, and uses `type_diff` to update focused text. Pauses
  commit spans and trim the window.
- `SpeechTranscriber` lazy-loads the selected ASR engine. Qwen supports
  commit-time `context=` bias; Nemotron MLX uses the shared post-correction path.
  It never applies find-replace rules.
- `hud_overlay.py` draws the in-process coral jelly-bar HUD. There is no
  subprocess HUD or review card.
- `dictation_history.py` stores the latest 50 final transcript texts locally.
  Dashboard edits create candidate context terms; explicit approval is required
  before a term enters `vocabulary.json`.

## User data

- `~/.qwen-dictation/config.json`: live settings only.
- `~/.qwen-dictation/vocabulary.json`: user-approved context terms.
- `~/.qwen-dictation/history.json`: latest 50 transcript texts, no audio.
- `~/.qwen-dictation/vocabulary-candidates.json`: candidate counts and dismissals.

Legacy user `dictionary.json` files are intentionally left untouched but are no
longer read. The max recording default is 300 seconds; legacy default `0` values
migrate once, while a later explicit user choice of `0` remains unlimited.

## Constraints

- Keep the app free, local-first, and macOS-focused.
- Preserve user data and unrelated working-tree edits.
- Keep Pretendard local; do not add CDN dependencies.
- Never commit model weights, `venv/`, caches, or `__pycache__/`.
