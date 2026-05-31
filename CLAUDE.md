# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Local-first macOS dictation app powered by **Qwen3-ASR** (not Whisper, despite the filename history). It runs as a menu-bar app, listens for a global hotkey, records mic audio, transcribes locally with Qwen, and types/pastes the result into whatever app is focused. A small Flask dashboard at `http://127.0.0.1:5001` edits settings and the personal dictionary.

The entry point is still named `whisper-dictation.py` — this project is a fork of whisper-dictation that swapped the STT backend to Qwen. Do **not** reintroduce Whisper code paths unless explicitly asked.

## Run

Always use the project virtualenv. `run.sh` activates `./venv` and forwards all args to the app:

```bash
./run.sh                       # default mode + model
./run.sh --mode streaming      # transcribe-while-recording, type the diff
./run.sh --mode batch_paste    # record, transcribe once, paste
./run.sh --mode batch_submit   # record, transcribe once, paste, press Return
./run.sh --model-size 0.6b     # default; also 1.7b
./run.sh --k_double_cmd        # double-press right Cmd to start, single press to stop
```

Default hotkey is `cmd_l+alt` (override with `-k/--key_combination`). Other flags: `-l/--language` (comma list, default `ko,en`), `-t/--max_time` (auto-stop seconds, default 30). Direct invocation without the wrapper: `./venv/bin/python whisper-dictation.py <args>`.

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
- **Hotkey listeners** (`pynput`) — `GlobalKeyListener` watches a two-key combo (`cmd_l+alt` default, parsed by splitting on `+`); `DoubleCommandKeyListener` is the `--k_double_cmd` variant (double-tap right Cmd to start, single to stop). Exactly one is chosen in `main()`.
- **`Recorder`** — owns the audio thread. `_record_impl` captures 16 kHz mono int16 via `pyaudio` into `audio_frames`; `_write_current_audio` flushes them to a `/tmp/*.wav` via `numpy`+`soundfile`. In `streaming` mode it also spawns `_stream_transcribe_loop`.
- **`SpeechTranscriber`** — wraps `qwen_asr.Qwen3ASRModel`. **Models lazy-load on first use per size and are cached** (`model_0_6b` / `model_1_7b`) behind a lock; device is **MPS if available else CPU**, dtype `float16` on MPS else `float32`. Model IDs come from `QWEN_ASR_0_6B_PATH` / `QWEN_ASR_1_7B_PATH` env vars (default to the HF `Qwen/Qwen3-ASR-*` repos).
- **Dashboard** (`dashboard.py`) — Flask daemon thread on **127.0.0.1:5001**, started by `start_server(app)` with a global ref to the `StatusBarApp`. Routes: `/` (renders `templates/dashboard.html`), `/api/config` GET/POST, `/api/status` GET, `/api/dictionary` GET/POST.
- **HUD** (`hud.py`) — a Tkinter floating overlay launched as a **separate subprocess** (`venv/bin/python hud.py`) by `Recorder._start_hud`, terminated on stop. It self-exits at `--max_time`.

The three modes are the core control flow:
- `streaming` re-transcribes the **whole growing buffer** every `stream_interval` and types only the diff via `type_diff` (backspace to the common prefix, then type the rest). Because it re-runs on the full buffer, latency grows with utterance length.
- `batch_paste` / `batch_submit` record to completion, transcribe once in `_run_batch_transcription`, then `paste_text` (submit also sends Return = AppleScript `key code 36`).

**Long-dictation review:** 단축키 배치(오른쪽 Cmd)는 결과를 곧장 붙여넣지 않고 화면 위쪽 리뷰 패널(`hud_overlay.show_review`)로 보여주며 키보드로 결정한다 — Enter=전송, 그 외 키=입력만(수정용), Esc=취소. 결정 로직은 순수 함수 `decide_review_action`, 상태는 `StatusBarApp.request_review`/`resolve_review`, 표시·키 리스너 관리는 메인스레드 `_tick_overlay`. `batch_submit` 모드(메뉴/대시보드 선택)는 여전히 리뷰 없이 바로 전송한다.

**Two ways text reaches the focused app, and they differ:** streaming uses `pynput` synthetic keystrokes (`type_diff`); batch uses `paste_text`, which `pbcopy`s then runs **AppleScript that clicks the front app's Paste menu** — Korean `붙여넣기`/`수정` first, then English `Paste`/`Edit`, and only falls back to synthetic `Cmd+V`. Menu-paste was chosen because Chrome accepted it more reliably. When touching paste/Return logic, validate with `e2e_prompt_test.py`, not just imports.

**Config persistence:** settings (mode/language/model/interval/max_time) are now persisted to `~/.qwen-dictation/config.json` via `app_config.py` (saved on change, loaded at startup). The user dictionary lives at `~/.qwen-dictation/dictionary.json`. The default model is **1.7b**. CLI flags still override on launch.

**Personal dictionary**: `dictionary.json` maps spoken→written replacements (e.g. `"큐엔": "Qwen"`), applied by `apply_dictionary` as plain `str.replace` over every transcript. Treat it as user-owned data — edit structure if needed but do not wipe the user's entries.

**Language handling**: `--language` is a comma list (default `ko,en`); the active one is mapped through `LANGUAGE_MAP` by `normalize_language` to a full name (`"ko"`→`"Korean"`) before being passed to the model. `auto` → `None`.

## Permissions (macOS)

The app needs **Microphone**, **Accessibility**, and **Automation** (control System Events) granted to the *terminal app* that launches it. Paste/Return failing → Accessibility/Automation missing; recording failing → Microphone missing.

## Project constraints

- Keep it **free and local-first** — no paid cloud STT APIs unless the user explicitly asks.
- Keep the app small and MVP-focused (menu bar + dashboard at 5001).
- `requirements.txt` and `pyproject.toml` (Poetry) are kept in sync; `poetry.lock` is committed.

See `AGENT.md` for the fuller product/runtime/testing/editing rules this summarizes.
