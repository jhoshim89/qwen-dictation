# Qwen Dictation

Local macOS dictation MVP powered by Qwen3-ASR. It runs from the menu bar, opens a small settings dashboard, and types into the currently focused input field.

## 받아쓰기 방식 (실시간 스트리밍)

실시간 스트리밍 단축키 2개 — 오른쪽 Cmd 홀드(누르는 동안) / 오른쪽 Option 토글(눌러 시작, 다시 눌러 정지). 말하는 대로 포커스된 입력창에 ~0.8초 간격으로 바로 타이핑되고, 문맥이 바뀌면 앞부분을 고쳐 쓰며, 쉬는 지점에서 확정한다. 리뷰 패널·배치·자동전송은 제거됨.

## Install

```bash
brew install portaudio
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
./run.sh
```

Dashboard:

```text
http://127.0.0.1:5001
```

기본 단축키는 두 개입니다.

- **오른쪽 Cmd 홀드**: 키를 누르고 있는 동안 받아쓰기, 떼면 정지.
- **오른쪽 Option 토글**: 한 번 눌러 시작, 다시 눌러 정지.

둘 다 똑같은 실시간 스트리밍으로 동작합니다. 말하는 대로 ~0.8초마다 포커스된
입력창에 바로 타이핑되고, 문맥이 바뀌면 앞부분을 backspace로 고쳐 쓰며, 잠깐
쉬는 지점에서 그 구간을 확정합니다.

## macOS Permissions

The app needs Microphone and Accessibility permissions because it listens to a
global hotkey, records audio, and types into the focused app.

1. Open **System Settings > Privacy & Security > Microphone**.
2. Enable the terminal app you use to run this project, such as Terminal, iTerm, or Codex.
3. Open **System Settings > Privacy & Security > Accessibility**.
4. Enable the same terminal app.
If typing does nothing, Accessibility is usually missing. If recording fails,
Microphone permission is usually missing.

## Word registration (vocabulary)

Register names and specialist terms in the dashboard. They are passed to Qwen as
recognition context on the next dictation. The list lives at
`~/.qwen-dictation/vocabulary.json`, one word or short phrase per entry.

Note: this biases recognition toward those words — it improves accuracy but is not a
guaranteed substitution. Legacy `dictionary.json` files are left untouched but
are no longer read or applied.

Example `vocabulary.json`:

```json
["Qwen", "각막", "궤양", "염색"]
```

## Recent dictation and vocabulary suggestions

The dashboard stores the latest 50 final transcript texts locally, without
audio. Correct a recent transcript inside the dashboard to create vocabulary
candidates. A candidate is only added to the Qwen context after explicit
approval. Repeated edits are recommended after two separate transcript records;
nothing is learned from typing performed in other apps.

## Hotkeys (configurable in the dashboard)

Choose a hold key and a toggle key from the right-side modifiers. They must
differ, and changes apply immediately without restart.

## Settings persistence

Settings (language, microphone, max recording time, and hotkeys) are saved to
`~/.qwen-dictation/config.json` and restored on next launch. Recording stops
after 300 seconds by default; set `max_time = 0` in advanced settings for no
limit.
The only model is **Qwen3-ASR 1.7B** (loads once on first dictation, then ~0.5s
per utterance).

## Brand system

The app's Warm Jelly Voice identity is documented in `DESIGN.md`. The selected
raspberry-jelly app icon source lives at `assets/AppIcon-source.png`; the flat
settings/menu-bar silhouette lives at `assets/logo-mark.svg`. Pretendard is
bundled locally under `assets/fonts/`. Run `./venv/bin/python make_icon.py`
after changing the icon source or menu-bar silhouette to rebuild
`assets/AppIcon.icns` and `assets/menubar.png`.

## Development Checks

```bash
./venv/bin/python -m py_compile whisper-dictation.py dashboard.py dictation_history.py hud_overlay.py
./venv/bin/pytest -q
./venv/bin/python - <<'PY'
import flask, numpy, pyaudio, pynput, qwen_asr, rumps, soundfile, torch
print("imports ok", torch.backends.mps.is_available())
PY
```

Pre-download the default model if the first run is slow:

```bash
HF_HUB_DISABLE_XET=1 HF_HUB_ENABLE_HF_TRANSFER=1 ./venv/bin/huggingface-cli download Qwen/Qwen3-ASR-1.7B
```

If that is slow or stalls, use the resumable parallel downloader:

```bash
./venv/bin/python download_qwen_model.py
```
