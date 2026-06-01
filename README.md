# Qwen Dictation

Local macOS dictation MVP powered by Qwen3-ASR. It runs from the menu bar, opens a small settings dashboard, and types into the currently focused input field.

## Modes

- **Streaming Dictation**: transcribes repeatedly while recording and types the visible diff.
- **Batch Paste**: records first, transcribes once, then pastes the result.
- **Batch Paste + Enter**: records first, transcribes once, pastes the result, then presses Return.

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

Useful options:

```bash
./run.sh --mode streaming
./run.sh --mode batch_paste
./run.sh --mode batch_submit
./run.sh --model-size 0.6b
./run.sh --model-size 1.7b
./run.sh --k_double_cmd
```

Default hotkey is `cmd_l+alt` on macOS. With `--k_double_cmd`, double press the right Command key to start and press it once to stop.

### Long dictation review (right Command)

After a long (batch) dictation via right Command, the result is NOT inserted
immediately. A review panel expands from the top of the screen showing the
transcript. Decide with the keyboard:

- **Right Command again (the toggle key) or Enter** → paste into the focused field and press Return (send)
- **Tab** → paste only (so you can edit in place, then send yourself)
- **Esc** → cancel (nothing is inserted; text stays on the clipboard)

The decision keys (toggle/Enter, Tab, Esc) are swallowed during review, so Tab does not move focus out of the target field.

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

## Personal Dictionary

Edit replacements in the dashboard or in `dictionary.json`.

Example:

```json
{
  "큐엔": "Qwen",
  "지피티": "GPT"
}
```

## Settings persistence

Settings (mode, language, model size, stream interval, max recording time) are
saved to `~/.qwen-dictation/config.json` and restored on next launch. The user
dictionary lives at `~/.qwen-dictation/dictionary.json`. Recording has no time
limit by default (`max_time = 0`); set a positive value to auto-stop.
The default model is **1.7b** (more accurate; ~0.2s slower than 0.6b once loaded).

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
