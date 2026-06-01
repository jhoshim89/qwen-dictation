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

Useful options:

```bash
./run.sh --k_double_cmd
```

With `--k_double_cmd`, double press the right Command key to start and press it once to stop.

## macOS Permissions

The app needs three macOS permissions because it listens to a global hotkey, records audio, and types into the focused app.

1. Open **System Settings > Privacy & Security > Microphone**.
2. Enable the terminal app you use to run this project, such as Terminal, iTerm, or Codex.
3. Open **System Settings > Privacy & Security > Accessibility**.
4. Enable the same terminal app.
5. Open **System Settings > Privacy & Security > Automation** if macOS prompts for it.
6. Allow the terminal app to control **System Events**.

If paste or Return does nothing, Accessibility or Automation is usually missing. If recording fails, Microphone permission is usually missing.

In testing, Chrome accepted menu-based paste more reliably than synthetic `Cmd+V`, so the app tries the front app's Edit/Paste menu first and falls back to `Cmd+V`.

## Word registration (vocabulary)

Instead of find-replace, you register words you say often (medical terms, names) in
the dashboard. These are passed to Qwen as recognition context so they are
transcribed correctly in the first place. The list lives at `vocabulary.json`
(one word per entry). On first run it is seeded from any existing `dictionary.json`
values plus the built-in veterinary terms.

Note: this biases recognition toward those words — it improves accuracy but is not a
guaranteed substitution like the old find-replace.

Example `vocabulary.json`:

```json
["Qwen", "각막", "궤양", "염색"]
```

## Hotkeys (configurable in the dashboard)

The dashboard lets you choose the hotkey mode and keys; changes save and apply
immediately (no restart):

- **multi** (default): a hold key (hold to dictate) + a toggle key (press to
  start, press again to stop). Both run the same real-time streaming dictation.
  Pick each from the right-side modifiers (right Option / Cmd / Ctrl / Shift);
  the two must differ. Default: hold = right Cmd, toggle = right Option.
- **single**: a two-key combo (set with `-k` at launch).
- **double**: double-press right Command.

CLI `--hotkeys` still overrides for a single run; omit it to use saved settings.

## Settings persistence

Settings (language, model, stream interval, max recording time, hotkey
mode/keys) are saved to `~/.qwen-dictation/config.json` and restored on next
launch. The word list lives at `~/.qwen-dictation/vocabulary.json`. Recording has
no time limit by default (`max_time = 0`); set a positive value to auto-stop.
The only model is **Qwen3-ASR 1.7B** (loads once on first dictation, then ~0.5s
per utterance).

## Development Checks

```bash
./venv/bin/python -m py_compile whisper-dictation.py dashboard.py hud.py test_typing.py
./venv/bin/python - <<'PY'
import flask, numpy, pyaudio, pynput, qwen_asr, rumps, soundfile, torch
print("imports ok", torch.backends.mps.is_available())
PY
```

Pre-download the default model if the first run is slow:

```bash
HF_HUB_DISABLE_XET=1 HF_HUB_ENABLE_HF_TRANSFER=1 ./venv/bin/huggingface-cli download Qwen/Qwen3-ASR-0.6B
```

If that is slow or stalls, use the resumable parallel downloader:

```bash
./venv/bin/python download_qwen_model.py
```

Check the paste/Return pipeline in a controlled prompt window:

```bash
./venv/bin/python e2e_prompt_test.py --text "Qwen paste test" --submit
```
