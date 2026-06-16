# ASR Engine Comparison Design

Date: 2026-06-16

## Goal

Make Qwen Dictation comparable across four ASR engines:

- `qwen`: existing default-quality local engine with context bias support.
- `nemotron_mlx`: existing Apple Silicon MLX engine, now selected in the running app.
- `google_stt`: new optional Google Speech-to-Text cloud engine.
- `sherpa_onnx_ko`: new optional local Korean sherpa-onnx engine.

The first implementation will make Google STT and sherpa-onnx selectable through the same dashboard and config flow as the existing engines. They will use the existing `SpeechTranscriber.transcribe_file()` path so all engines can be compared under the current streaming loop before any deeper streaming rewrite.

## Current State

- The running app config is set to `asr_engine: "nemotron_mlx"`.
- `asr_engines.py` currently defines `qwen` and `nemotron_mlx`.
- The dashboard already renders engine choices from `/api/config`.
- `mlx_audio` is installed.
- `google.cloud.speech` is not installed in the app virtualenv.
- `sherpa_onnx` is not installed in the app virtualenv.
- `gcloud` has an account and project configured: project `claude-sheets-495601`.
- Application Default Credentials are missing.
- `GOOGLE_APPLICATION_CREDENTIALS` is not set.
- The credentials found from `budget-dashboard` are Google Sheets/Drive OAuth credentials, not Speech-to-Text credentials.
- `speech.googleapis.com` did not appear in the enabled-service check output for the configured project.

## Architecture

Keep the current engine boundary:

- `asr_engines.py` owns engine ids, display labels, model identifiers, aliases, capability flags, and language normalization helpers.
- `SpeechTranscriber` owns lazy model/client loading and `transcribe_file()` dispatch.
- `Recorder` continues to feed WAV windows through `_transcribe_window()` and does not need to know engine-specific details.
- Dashboard/config code continues to treat `asr_engine` as a normalized engine id.

Add two engine ids:

- `ASR_ENGINE_GOOGLE_STT = "google_stt"`
- `ASR_ENGINE_SHERPA_ONNX_KO = "sherpa_onnx_ko"`

Add capability metadata:

- `supports_context`: false for both new engines in the first implementation.
- `requires_network`: true for Google STT, false for sherpa.
- `requires_credentials`: true for Google STT, false for sherpa.
- `local`: false for Google STT, true for sherpa.

## Google STT Design

Use `google-cloud-speech` as an optional dependency. Do not import it at module import time. Import only when `google_stt` is selected and transcription is requested.

Initial recognition path:

- Read the existing 16 kHz mono WAV window written by `_transcribe_window()`.
- Use Google Speech-to-Text v1 `SpeechClient.recognize()` for a synchronous comparison path.
- Configure language as `ko-KR` for Korean, `en-US` for English, and `ko-KR` for auto in this first pass.
- Use `LINEAR16`, sample rate 16000, automatic punctuation enabled.
- Use model `latest_long` for general dictation unless the API rejects the model; if rejected, fall back to the default model and surface the fallback in logs.

Authentication behavior:

- Prefer normal Google ADC resolution: `GOOGLE_APPLICATION_CREDENTIALS`, then gcloud ADC.
- Do not read or store credential secrets in Qwen Dictation config.
- If credentials are missing, raise a clear runtime error explaining that `gcloud auth application-default login` or a Speech-enabled service account JSON is required.
- If the Speech API is disabled, surface the Google error without crashing the menu-bar app.

This first pass is a cloud comparison engine, not a final low-latency streaming integration.

## sherpa-onnx Korean Design

Use `sherpa-onnx` as an optional dependency. Do not import it at module import time.

Model:

- Default model id: `k2-fsa/sherpa-onnx-streaming-zipformer-korean-2024-06-16`.
- Local model root: `~/.qwen-dictation/models/sherpa-onnx-streaming-zipformer-korean-2024-06-16`.
- Prefer int8 files if present because this is a local interactive dictation app.

Initial recognition path:

- Add a small model locator helper that checks for required ONNX/token files under the local model root.
- If files are missing, raise a clear runtime error with the install command or helper script name.
- Use sherpa-onnx online recognizer APIs to decode the WAV window in the same `transcribe_file()` interface used by Qwen and Nemotron.
- Keep the existing app-level silence gate before invoking sherpa.

This first pass uses the existing windowed path for fair comparison. A second implementation can wire sherpa's streaming recognizer state directly into `Recorder` after the file-path comparison proves useful.

## Config And UI

Expose both new engines through the existing dashboard engine selector. The dashboard should require no special layout change because it already renders the engine list from backend metadata.

Config normalization should accept practical aliases:

- Google: `google`, `google_stt`, `gcp`, `speech_to_text`
- sherpa: `sherpa`, `sherpa_onnx`, `sherpa_onnx_ko`, `zipformer_ko`

Existing saved configs with `qwen` or `nemotron_mlx` must keep working.

## Error Handling

Engine failures must not kill the menu-bar app.

- Missing Python package: explain which install script or package is needed.
- Missing Google credentials: explain ADC/service-account requirement.
- Disabled Google Speech API or permission failure: surface the Google error in logs and notification text.
- Missing sherpa model files: explain where the model should live.
- Empty recognition result: return an empty string, matching existing behavior.

## Testing

Add focused tests for:

- Engine metadata includes `qwen`, `nemotron_mlx`, `google_stt`, and `sherpa_onnx_ko`.
- Engine aliases normalize correctly.
- Google language normalization maps Korean and English to Google language codes.
- Google transcribe dispatch calls a fake Google client with the expected config.
- Missing Google package or credentials produces a clear runtime error.
- sherpa transcribe dispatch calls a fake recognizer/model wrapper.
- Missing sherpa package or model files produces a clear runtime error.
- Config API accepts the new engine ids and updates the recorder transcriber.

Verification commands:

- `./venv/bin/python -m py_compile whisper-dictation.py asr_engines.py app_config.py dashboard.py`
- `./venv/bin/python -m pytest -q`
- If packaging-related files change, run `./build_app.sh` and codesign verification.

## Out Of Scope

- Native Google streaming gRPC integration.
- Native sherpa streaming state inside `Recorder`.
- Storing Google credentials in Qwen Dictation config.
- Making Google STT the default engine.
- Removing Qwen or Nemotron.

## Rollout

1. Keep current running app on `nemotron_mlx`.
2. Add engine metadata and normalization.
3. Add optional Google STT dispatch.
4. Add optional sherpa dispatch and model locator.
5. Add tests.
6. Run verification.
7. Rebuild/relaunch only if packaging or installed dependency behavior requires it.
