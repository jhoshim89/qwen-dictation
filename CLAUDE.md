# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Local-first macOS dictation app powered by **Qwen3-ASR** (not Whisper, despite the filename history). It runs as a menu-bar app, listens for a global hotkey, records mic audio, transcribes locally with Qwen, and types/pastes the result into whatever app is focused. A small Flask dashboard at `http://127.0.0.1:5001` edits settings, the word list, and hotkeys.

The entry point is still named `whisper-dictation.py` — this project is a fork of whisper-dictation that swapped the STT backend to Qwen. Do **not** reintroduce Whisper code paths unless explicitly asked.

## Run

Always use the project virtualenv. `run.sh` activates `./venv` and forwards all args to the app:

```bash
./run.sh                       # live streaming dictation (default)
./run.sh --hotkeys double      # double-press right Cmd (overrides saved hotkey mode for this run)
./run.sh --k_double_cmd        # double-press right Cmd to start, single press to stop
```

Both hotkeys always drive **live streaming dictation** — there is no batch path anymore (the `--mode {streaming,batch_paste,batch_submit}` arg and the menu "Mode: …" items are leftover dead code; the hotkey listeners begin every session as `MODE_STREAMING`). The default multi-hotkey config is hold = right Cmd, toggle = right Option. Other flags: `-l/--language` (comma list, default `ko,en`), `-t/--max_time` (auto-stop seconds, default 30). Direct invocation without the wrapper: `./venv/bin/python whisper-dictation.py <args>`.

## Verify changes (run before claiming the app works)

```bash
# 1. compile / import sanity
./venv/bin/python -m py_compile whisper-dictation.py dashboard.py hud.py test_typing.py
./venv/bin/python - <<'PY'
import flask, numpy, pyaudio, pynput, qwen_asr, rumps, soundfile, torch
print("imports ok", torch.backends.mps.is_available())
PY

# 2. the paste/Return pipeline in a controlled prompt window
./venv/bin/python e2e_prompt_test.py --text "Qwen paste test" --submit

# 3. typing/keystroke unit-ish check
./venv/bin/python test_typing.py
```

There is no pytest suite — verification is these scripts plus a real Qwen transcription on a local audio file. If macOS blocks input automation, report the exact missing permission rather than calling the app broken.

## Model weights

Pre-download to avoid a slow first run:

```bash
HF_HUB_DISABLE_XET=1 HF_HUB_ENABLE_HF_TRANSFER=1 ./venv/bin/huggingface-cli download Qwen/Qwen3-ASR-0.6B
./venv/bin/python download_qwen_model.py   # resumable parallel fallback if the above stalls
```

Never commit model weights, `venv/`, caches, or `__pycache__/`.

## Architecture (big picture)

`whisper-dictation.py` is a single long-running process (`main()`) that wires together the pieces below. `StatusBarApp` (a `rumps.App`) is the central state object — `mode`, `current_language`, `selected_model`, `stream_interval`, `max_time`, `started` all live on it. Both the hotkey listeners and the dashboard mutate this one object, so it's the source of truth.

- **`StatusBarApp`** — menu-bar UI + run loop. Holds runtime config and the `Recorder`. `toggle()` / `start_app` / `stop_app` drive recording; `update_title()` shows the elapsed timer.
- **Hotkey listeners** (`pynput`) — `MultiHotkeyListener` (the default) watches two keys: **hold = right Cmd (`cmd_r`)**, **toggle = right Option (`alt_r`)**. Hold dictates while held; toggle starts/stops. **Both call `_begin(..., MODE_STREAMING)`** — there is only one streaming path. `GlobalKeyListener` (single two-key combo) and `DoubleCommandKeyListener` (`--k_double_cmd`) are the alternative listeners; exactly one is chosen via `hotkey_mode` in `build_key_listener()`.
- **`Recorder`** — owns the audio thread. `_record_impl` captures 16 kHz mono int16 via `pyaudio` into `audio_frames`; `_write_current_audio` flushes them to a `/tmp/*.wav` via `numpy`+`soundfile`. It always spawns the live streaming loop `_stream_loop`/`_stream_tick` (see below).
- **`SpeechTranscriber`** — wraps `qwen_asr.Qwen3ASRModel`. **Only the 1.7B model is used** (lazy-loaded once and cached as `model_1_7b` behind a lock; `get_model` ignores size and returns it); device is **MPS if available else CPU**, dtype `float16` on MPS else `float32`. `transcribe_file` passes the user's word list as `context=` to bias recognition. Model ID comes from `QWEN_ASR_1_7B_PATH` env var (default HF `Qwen/Qwen3-ASR-1.7B`). 0.6B was removed.
- **Dashboard** (`dashboard.py`) — Flask daemon thread on **127.0.0.1:5001**, started by `start_server(app)` with a global ref to the `StatusBarApp`. Routes: `/` (renders `templates/dashboard.html`), `/api/config` GET/POST (incl. hotkey_mode/hold_key/toggle_key; POST applies hotkeys at runtime), `/api/status` GET, `/api/vocabulary` GET/POST (word list).
- **HUD** (`hud.py`) — a Tkinter floating overlay launched as a **separate subprocess** (`venv/bin/python hud.py`) by `Recorder._start_hud`, terminated on stop. It self-exits at `--max_time`.

**The single control flow is live streaming.** Both triggers (Cmd hold, Option toggle) run the same path: `Recorder._stream_loop` wakes every `STREAM_INTERVAL` (0.8s) and calls `_stream_tick`, which transcribes the current audio **window** and types only the diff via `type_diff` (backspace to the common prefix, then type the rest). On a pause it confirms (commits) the spoken span and trims the window so latency doesn't grow without bound. The pure helpers and constants live near the top of `whisper-dictation.py`: `STREAM_INTERVAL` (0.8s tick), `PAUSE_SILENCE_SEC` (0.8s of trailing quiet = a pause), `MAX_WINDOW_SEC` (12s hard cap that forces a commit); `trailing_silence(...)` measures end-of-window quiet and `should_commit(...)` decides when to confirm+trim.

**Batch / review path is removed.** `_run_batch_transcription` was deleted; nothing triggers the review panel anymore. The `MODE_BATCH_PASTE`/`MODE_BATCH_SUBMIT` constants, the "Mode: Batch …" menu items, and the review machinery (`decide_review_action`, `StatusBarApp.request_review`/`resolve_review`, `paste_text`) **remain as dead code but are never reached at runtime**. Don't document them as live behavior.

**Text reaches the focused app one way:** live streaming types `pynput` synthetic keystrokes via `type_diff`. (`paste_text` — `pbcopy` + AppleScript Paste-menu click with `Cmd+V` fallback — still exists in the file but is only called by the now-unreachable review path.)

**Config persistence:** settings (mode/language/model/interval/max_time + hotkey_mode/hold_key/toggle_key) are persisted to `~/.qwen-dictation/config.json` via `app_config.py` (saved on change, loaded at startup; stale `0.6b` is coerced to `1.7b`). The word list lives at `~/.qwen-dictation/vocabulary.json`. The only model is **1.7b**. CLI flags still override on launch; `--hotkeys` defaults to None (omit = use saved).

**Word registration (vocabulary)**: `vocabulary.py` holds a user word list (`vocabulary.json`, a JSON array). `transcribe_file` joins it and passes it as `context=` to `model.transcribe`, biasing recognition toward those terms (medical terms, names) — this **improves** recognition but is not a guaranteed substitution. `ensure_vocabulary()` seeds it once from any existing `dictionary.json` values + `vet_terms.VET_TERMS` values. The old find-replace `apply_dictionary`/`ensure_dictionary`/`merge_vet_terms` were removed. Treat the word list as user-owned data.

**Configurable hotkeys**: `StatusBarApp.build_key_listener()` picks the listener from `hotkey_mode` (multi/single/double); the multi default is **hold = `cmd_r`, toggle = `alt_r`**, both starting `MODE_STREAMING`. `apply_hotkey_config()` stops the running global pynput listener and starts a fresh one, so dashboard changes apply without restart. `key_from_name`/`validate_hotkey_config` are pure helpers; allowed keys are right-side modifiers (`alt_r`/`cmd_r`/`ctrl_r`/`shift_r`), and multi requires hold≠toggle.

**Language handling**: `--language` is a comma list (default `ko,en`); the active one is mapped through `LANGUAGE_MAP` by `normalize_language` to a full name (`"ko"`→`"Korean"`) before being passed to the model. `auto` → `None`.

## Permissions (macOS)

The app needs **Microphone**, **Accessibility**, and **Automation** (control System Events) granted to the *terminal app* that launches it. Paste/Return failing → Accessibility/Automation missing; recording failing → Microphone missing.

## Project constraints

- Keep it **free and local-first** — no paid cloud STT APIs unless the user explicitly asks.
- Keep the app small and MVP-focused (menu bar + dashboard at 5001).
- `requirements.txt` and `pyproject.toml` (Poetry) are kept in sync; `poetry.lock` is committed.

See `AGENT.md` for the fuller product/runtime/testing/editing rules this summarizes.
