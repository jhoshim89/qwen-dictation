import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import time

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

import numpy as np
import pyaudio
import rumps
import soundfile as sf
import torch
from pynput import keyboard
from qwen_asr import Qwen3ASRModel

import dashboard
import app_paths
import app_config
import vet_terms
import vocabulary
import audio_level
import hud_overlay
import settings_window


APP_DIR = os.path.dirname(os.path.abspath(__file__))
DICTIONARY_PATH = app_paths.dictionary_path()
MODE_STREAMING = "streaming"
MODE_BATCH_PASTE = "batch_paste"
MODE_BATCH_SUBMIT = "batch_submit"
SUPPORTED_MODES = (MODE_STREAMING, MODE_BATCH_PASTE, MODE_BATCH_SUBMIT)
MODEL_0_6B = os.environ.get("QWEN_ASR_0_6B_PATH", "Qwen/Qwen3-ASR-0.6B")
MODEL_1_7B = os.environ.get("QWEN_ASR_1_7B_PATH", "Qwen/Qwen3-ASR-1.7B")
LANGUAGE_MAP = {
    "auto": None,
    "ko": "Korean",
    "kr": "Korean",
    "korean": "Korean",
    "en": "English",
    "english": "English",
    "zh": "Chinese",
    "chinese": "Chinese",
    "ja": "Japanese",
    "jp": "Japanese",
    "japanese": "Japanese",
}


def safe_notify(title, subtitle, message):
    try:
        rumps.notification(title, subtitle, message)
    except Exception as exc:
        print(f"Notification error (non-fatal): {exc}")


def normalize_language(language):
    if not language:
        return None
    if isinstance(language, list):
        language = language[0] if language else None
    language = str(language).strip()
    if not language:
        return None
    return LANGUAGE_MAP.get(language.lower(), language)



# 리뷰 패널에서 누른 키 → 행동 결정.
def decide_review_action(key, toggle_key=None):
    """리뷰 중 눌린 키로 행동을 정한다.

    Enter 또는 토글키(녹음 시작/정지에 쓰던 그 키)를 다시 누름 → "send"(붙여넣고 전송),
    Tab → "insert"(붙여넣기만, 사용자가 직접 고친 뒤 전송),
    Esc → "cancel"(아무것도 안 함). 그 외 키는 무시(None) — 결정은 이 키들로만 한다.
    """
    if key == keyboard.Key.enter:
        return "send"
    if toggle_key is not None and key == toggle_key:
        return "send"
    if key == keyboard.Key.tab:
        return "insert"
    if key == keyboard.Key.esc:
        return "cancel"
    return None


def paste_text(text, submit=False):
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    submit_line = "key code 36" if submit else ""
    script = f"""
    tell application "System Events"
        set frontApp to first process whose frontmost is true
        set pasted to false
        try
            click menu item "붙여넣기" of menu "수정" of menu bar 1 of frontApp
            set pasted to true
        end try
        if pasted is false then
            try
                click menu item "Paste" of menu "Edit" of menu bar 1 of frontApp
                set pasted to true
            end try
        end if
        if pasted is false then
            keystroke "v" using command down
        end if
        delay 0.12
        {submit_line}
    end tell
    """
    subprocess.run(["osascript", "-e", script], check=True)


def type_diff(old_text, new_text, keyboard_controller):
    old_text = old_text.strip()
    new_text = new_text.strip()
    if not new_text:
        return old_text
    if not old_text:
        keyboard_controller.type(new_text)
        return new_text
    if new_text.startswith(old_text):
        diff = new_text[len(old_text):]
        if diff:
            keyboard_controller.type(diff)
            return new_text
        return old_text

    common_prefix = os.path.commonprefix([old_text, new_text])
    backspaces = len(old_text) - len(common_prefix)
    for _ in range(backspaces):
        keyboard_controller.press(keyboard.Key.backspace)
        keyboard_controller.release(keyboard.Key.backspace)
        time.sleep(0.001)
    diff = new_text[len(common_prefix):]
    if diff:
        keyboard_controller.type(diff)
        return new_text
    return old_text


class SpeechTranscriber:
    def __init__(self, device, dtype):
        self.device = device
        self.dtype = dtype
        self.pykeyboard = keyboard.Controller()
        self.model_0_6b = None
        self.model_1_7b = None
        self.model_lock = threading.Lock()

    def get_model(self, model_size):
        with self.model_lock:
            if model_size == "1.7b":
                if self.model_1_7b is None:
                    safe_notify("Qwen Dictation", "Loading model", "Qwen3-ASR-1.7B 모델을 불러옵니다.")
                    self.model_1_7b = Qwen3ASRModel.from_pretrained(
                        MODEL_1_7B,
                        dtype=self.dtype,
                    )
                    self.model_1_7b.model.to(self.device)
                    self.model_1_7b.device = self.device
                return self.model_1_7b

            # 0.6b 는 제거됨 — 항상 1.7b 사용.
            return self.model_1_7b

    def transcribe_file(self, audio_path, language=None, model_size="1.7b"):
        model = self.get_model(model_size)
        language = normalize_language(language)
        context = vocabulary.build_context(vocabulary.load_vocabulary())
        results = model.transcribe(audio_path, context=context, language=language)
        if not results:
            return ""
        return results[0].text.strip()


class Recorder:
    def __init__(self, transcriber, app):
        self.transcriber = transcriber
        self.app = app
        self.recording = False
        self.audio_frames = []
        self.audio_lock = threading.Lock()
        self.record_thread = None
        self.stream_thread = None
        self.hud_process = None

    def start(self, language=None):
        if self.recording:
            return
        self.audio_frames = []
        self.recording = True
        self._start_hud()
        self.record_thread = threading.Thread(target=self._record_impl, args=(language,), daemon=True)
        self.record_thread.start()
        if self.app.mode == MODE_STREAMING:
            self.stream_thread = threading.Thread(target=self._stream_transcribe_loop, args=(language,), daemon=True)
            self.stream_thread.start()

    def stop(self):
        self.recording = False
        self._stop_hud()
        audio_level.clear_level()

    def _start_hud(self):
        # Overlay is now driven in-process by StatusBarApp._tick_overlay
        pass

    def _stop_hud(self):
        # Overlay is now driven in-process by StatusBarApp._tick_overlay
        pass

    def _record_impl(self, language):
        safe_notify("Qwen Dictation", "Recording", "말을 마친 뒤 단축키를 다시 눌러주세요.")
        frames_per_buffer = 1024
        pyaudio_instance = pyaudio.PyAudio()
        stream = pyaudio_instance.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            frames_per_buffer=frames_per_buffer,
            input=True,
        )

        while self.recording:
            try:
                data = stream.read(frames_per_buffer, exception_on_overflow=False)
                with self.audio_lock:
                    self.audio_frames.append(data)
                audio_level.write_level(audio_level.compute_rms(data))
            except Exception as exc:
                print(f"Audio read error: {exc}")

        stream.stop_stream()
        stream.close()
        pyaudio_instance.terminate()

        if self.app.mode != MODE_STREAMING:
            self._run_batch_transcription(language)

    def _write_current_audio(self, path):
        with self.audio_lock:
            frames = list(self.audio_frames)
        if not frames:
            return False
        audio_data = np.frombuffer(b"".join(frames), dtype=np.int16)
        audio_data_fp32 = audio_data.astype(np.float32) / 32768.0
        sf.write(path, audio_data_fp32, 16000)
        return True

    def _run_batch_transcription(self, language):
        audio_path = "/tmp/qwen_dictation_batch.wav"
        if not self._write_current_audio(audio_path):
            return
        try:
            safe_notify("Qwen Dictation", "Transcribing", "Qwen3-ASR로 녹음 전체를 분석 중입니다.")
            text = self.transcriber.transcribe_file(
                audio_path,
                language=language,
                model_size=self.app.selected_model,
            )
            if not text:
                return
            if self.app.mode == MODE_BATCH_SUBMIT:
                # 메뉴/대시보드로 명시적으로 '자동 전송'을 고른 경우엔 리뷰 없이 바로 전송.
                paste_text(text, submit=True)
                safe_notify("Qwen Dictation", "Done", text)
            else:
                # 단축키(오른쪽 Cmd) 배치: 리뷰 패널로 보여주고 사용자가 결정.
                subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
                self.app.request_review(text)
        except Exception as exc:
            print(f"Batch transcription error: {exc}")
            safe_notify("Qwen Dictation", "Error", str(exc))

    def _stream_transcribe_loop(self, language):
        last_text = ""
        time.sleep(1.0)
        while self.recording:
            time.sleep(self.app.stream_interval)
            audio_path = "/tmp/qwen_dictation_stream.wav"
            if not self._write_current_audio(audio_path):
                continue
            try:
                new_text = self.transcriber.transcribe_file(
                    audio_path,
                    language=language,
                    model_size=self.app.selected_model,
                )
                if new_text:
                    last_text = type_diff(last_text, new_text, self.transcriber.pykeyboard)
            except Exception as exc:
                print(f"Streaming transcription error: {exc}")


class GlobalKeyListener:
    def __init__(self, app, key_combination):
        self.app = app
        self.key1, self.key2 = self.parse_key_combination(key_combination)
        self.key1_pressed = False
        self.key2_pressed = False

    def parse_key_combination(self, key_combination):
        parts = key_combination.split("+")

        def resolve(name):
            return getattr(keyboard.Key, name, keyboard.KeyCode(char=name))

        key1 = resolve(parts[0])
        key2 = resolve(parts[1]) if len(parts) > 1 else None
        return key1, key2

    def on_key_press(self, key):
        # Single-key hotkey: toggle on that one key.
        if self.key2 is None:
            if key == self.key1:
                self.app.toggle()
            return

        if key == self.key1:
            self.key1_pressed = True
        elif key == self.key2:
            self.key2_pressed = True
        if self.key1_pressed and self.key2_pressed:
            self.app.toggle()

    def on_key_release(self, key):
        if self.key2 is None:
            return
        if key == self.key1:
            self.key1_pressed = False
        elif key == self.key2:
            self.key2_pressed = False


class DoubleCommandKeyListener:
    def __init__(self, app):
        self.app = app
        self.key = keyboard.Key.cmd_r
        self.last_press_time = 0

    def on_key_press(self, key):
        if key != self.key:
            return
        current_time = time.time()
        if self.app.started:
            self.app.toggle()
        elif current_time - self.last_press_time < 0.5:
            self.app.toggle()
        self.last_press_time = current_time

    def on_key_release(self, key):
        pass


class MultiHotkeyListener:
    """오른쪽 단일 수정키 2개로 두 받아쓰기 모드를 구동한다.

    - 오른쪽 Option(alt_r): 홀드 — 누르는 동안만 녹음, 떼면 정지 → streaming(짧은 말)
    - 오른쪽 Cmd(cmd_r): 토글 — 눌러 시작, 다시 눌러 정지 → batch_paste(긴 말, 붙여넣고 멈춤)

    동시에 하나의 트리거만 활성(active_trigger). 녹음 중 다른 트리거 키는 무시한다.
    자동 전송(batch_submit)은 단축키에 배정하지 않는다 — 사용자가 결과를 보고 직접 처리.
    """

    def __init__(self, app):
        self.app = app
        self.hold_key = keyboard.Key.alt_r
        self.toggle_key = keyboard.Key.cmd_r
        self.active_trigger = None  # None | "hold" | "toggle"

    def _begin(self, trigger, mode):
        if self.app.started:
            return
        self.app.begin_session(mode)
        self.active_trigger = trigger

    def _end(self, trigger):
        if self.active_trigger != trigger:
            return
        if self.app.started:
            self.app.stop_app(None)
        self.active_trigger = None

    def on_key_press(self, key):
        if key == self.hold_key:
            if not self.app.started:
                self._begin("hold", MODE_STREAMING)
        elif key == self.toggle_key:
            if self.active_trigger == "toggle":
                self._end("toggle")
            elif not self.app.started:
                self._begin("toggle", MODE_BATCH_PASTE)

    def on_key_release(self, key):
        if key == self.hold_key:
            self._end("hold")


class StatusBarApp(rumps.App):
    def __init__(self, languages=None, max_time=None, mode=MODE_STREAMING):
        _mb = app_paths.resource_path("assets", "menubar.png")
        if os.path.exists(_mb):
            super().__init__("Qwen Dictation", icon=_mb, template=True)
        else:
            super().__init__("Qwen Dictation", "⏯")
        self.languages = languages or ["ko", "en"]
        self.current_language = self.languages[0]
        self.mode = mode
        self.selected_model = "1.7b"
        self.stream_interval = 1.2
        self.k_double_cmd = False
        self.started = False
        self.pending_review_text = None
        self.review_active = False
        self._review_shown = False
        self._review_suppress = False
        self.recorder = None
        self.max_time = max_time
        self.timer = None
        self.elapsed_time = 0
        self.start_time = None

        menu = [
            "Start Recording",
            "Stop Recording",
            None,
            rumps.MenuItem("Mode: Streaming", callback=self.set_streaming_mode),
            rumps.MenuItem("Mode: Batch Paste", callback=self.set_batch_paste_mode),
            rumps.MenuItem("Mode: Batch Paste + Enter", callback=self.set_batch_submit_mode),
            None,
            rumps.MenuItem("Open Settings Dashboard", callback=self.open_dashboard),
            None,
        ]
        for lang in self.languages:
            menu.append(rumps.MenuItem(f"Language: {lang}", callback=self.change_language))
        self.menu = menu
        self.menu["Stop Recording"].set_callback(None)
        self.sync_menu_state()
        self._apply_saved_config()

        # Always-running main-thread timer that drives the in-process native
        # overlay. Its callback runs on the rumps/AppKit main thread, so it is
        # the only place allowed to create/mutate the overlay window.
        self._overlay_timer = rumps.Timer(self._tick_overlay, 0.15)
        self._overlay_timer.start()

    def _tick_overlay(self, _):
        try:
            ov = hud_overlay.get_overlay()
            if self.review_active:
                # 리뷰 패널 표시(키 입력은 항상 켜진 메인 리스너가 처리)
                if not getattr(self, "_review_shown", False):
                    ov.show_review(self.pending_review_text or "")
                    self._review_shown = True
                return
            # 리뷰가 끝났으면 패널 원복
            if getattr(self, "_review_shown", False):
                self._review_shown = False
                ov.hide()
            if self.started and self.start_time is not None:
                elapsed = int(time.time() - self.start_time)
                ov.update(audio_level.read_level(), elapsed)
                ov.show()
            else:
                ov.hide()
        except Exception as exc:
            print(f"overlay tick error: {exc}")

    def current_config(self):
        return {
            "mode": self.mode,
            "language": self.current_language,
            "model_size": self.selected_model,
            "stream_interval": self.stream_interval,
            "max_time": self.max_time or 0,
        }

    def save_settings(self):
        app_config.save_config(self.current_config())

    def _apply_saved_config(self):
        cfg = app_config.load_config()
        self.mode = cfg["mode"]
        self.current_language = cfg["language"]
        self.selected_model = cfg["model_size"]
        self.stream_interval = cfg["stream_interval"]
        self.max_time = cfg["max_time"]
        self.sync_menu_state()

    def sync_menu_state(self):
        self.menu["Mode: Streaming"].state = int(self.mode == MODE_STREAMING)
        self.menu["Mode: Batch Paste"].state = int(self.mode == MODE_BATCH_PASTE)
        self.menu["Mode: Batch Paste + Enter"].state = int(self.mode == MODE_BATCH_SUBMIT)
        for lang in self.languages:
            self.menu[f"Language: {lang}"].state = int(self.current_language == lang)

    def open_dashboard(self, _):
        settings_window.open_settings("http://127.0.0.1:5001")

    def set_mode(self, mode):
        if mode not in SUPPORTED_MODES:
            raise ValueError(f"Unsupported mode: {mode}")
        if self.started:
            raise RuntimeError("Cannot change mode while recording")
        self.mode = mode
        self.sync_menu_state()
        self.save_settings()

    def set_streaming_mode(self, _):
        self.set_mode(MODE_STREAMING)

    def set_batch_paste_mode(self, _):
        self.set_mode(MODE_BATCH_PASTE)

    def set_batch_submit_mode(self, _):
        self.set_mode(MODE_BATCH_SUBMIT)

    def change_language(self, sender):
        self.current_language = sender.title.replace("Language: ", "")
        self.sync_menu_state()
        self.save_settings()

    @rumps.clicked("Start Recording")
    def start_app(self, _):
        if self.started:
            return
        print("Listening...")
        self.started = True
        self.menu["Start Recording"].set_callback(None)
        self.menu["Stop Recording"].set_callback(self.stop_app)
        self.recorder.start(self.current_language)
        if self.max_time and self.max_time > 0:
            self.timer = threading.Timer(self.max_time, lambda: self.stop_app(None))
            self.timer.start()
        self.start_time = time.time()
        self.update_title()

    @rumps.clicked("Stop Recording")
    def stop_app(self, _):
        if not self.started:
            return
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        self.title = None
        self.started = False
        self.menu["Stop Recording"].set_callback(None)
        self.menu["Start Recording"].set_callback(self.start_app)
        self.recorder.stop()
        print("Stopped.")

    def update_title(self):
        if self.started and self.start_time is not None:
            self.elapsed_time = int(time.time() - self.start_time)
            minutes, seconds = divmod(self.elapsed_time, 60)
            self.title = f"({minutes:02d}:{seconds:02d}) 🔴"
            threading.Timer(1, self.update_title).start()

    def toggle(self):
        if self.started:
            self.stop_app(None)
        else:
            self.start_app(None)

    def begin_session(self, mode):
        """단축키가 이번 녹음에만 모드를 적용하고 시작한다(저장하지 않음).

        영속 기본 모드(app_config)는 그대로 두고, 세션 동안만 mode 를 바꾼다.
        """
        if self.started:
            return
        self.mode = mode
        self.sync_menu_state()
        self.start_app(None)

    def request_review(self, text):
        """배치 받아쓰기 결과를 리뷰 대기 상태로 보관한다(아직 붙여넣지 않음)."""
        self.pending_review_text = text
        self.review_active = True

    def resolve_review(self, action):
        """리뷰 결정 실행. action: 'send' | 'insert' | 'cancel'."""
        if not self.review_active:
            return
        text = self.pending_review_text or ""
        self.review_active = False
        self.pending_review_text = None
        if action == "send":
            paste_text(text, submit=True)
        elif action == "insert":
            paste_text(text, submit=False)
        # 'cancel' 은 아무 것도 안 함


def parse_args():
    parser = argparse.ArgumentParser(description="Local Qwen3-ASR dictation app for macOS.")
    parser.add_argument(
        "-k",
        "--key_combination",
        type=str,
        default="cmd_l+alt" if platform.system() == "Darwin" else "ctrl+alt",
        help="Hotkey to toggle recording, for example cmd_l+alt.",
    )
    parser.add_argument(
        "--k_double_cmd",
        action="store_true",
        help="Use double right Command to start and single right Command to stop.",
    )
    parser.add_argument(
        "-l",
        "--language",
        type=str,
        default="ko,en",
        help="Comma-separated language choices. First item is used initially.",
    )
    parser.add_argument("-t", "--max_time", type=float, default=0)
    parser.add_argument("--mode", choices=SUPPORTED_MODES, default=MODE_STREAMING)
    parser.add_argument(
        "--hotkeys",
        choices=("multi", "single", "double"),
        default="multi",
        help="multi=right Option(hold)/right Cmd(toggle) single keys (default); single=-k combo; double=double right Cmd.",
    )
    parser.add_argument("--model-size", choices=("1.7b",), default="1.7b")
    return parser.parse_args()


def main():
    args = parse_args()
    vocabulary.ensure_vocabulary()
    languages = [item.strip() for item in args.language.split(",") if item.strip()]
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device == "mps" else torch.float32
    print(f"Initializing Qwen3-ASR on {device}...")

    app = StatusBarApp(languages=languages, max_time=args.max_time, mode=args.mode)
    app.k_double_cmd = args.k_double_cmd
    transcriber = SpeechTranscriber(device, dtype)
    recorder = Recorder(transcriber, app)
    app.recorder = recorder

    dashboard.start_server(app)
    if args.k_double_cmd or args.hotkeys == "double":
        key_listener = DoubleCommandKeyListener(app)
    elif args.hotkeys == "single":
        key_listener = GlobalKeyListener(app, args.key_combination)
    else:
        key_listener = MultiHotkeyListener(app)
    def on_review_or_hotkey(key):
        # 리뷰 중이면 키를 결정(보내기/수정/취소)으로 가로채고, 아니면 평소 단축키 처리.
        if app.review_active:
            toggle_key = getattr(key_listener, "toggle_key", None)
            action = decide_review_action(key, toggle_key=toggle_key)
            if action is not None:
                # 이 키가 포커스된 앱으로 새지 않게 표시(아래 intercept 에서 폐기).
                app._review_suppress = True
                app.resolve_review(action)
            return
        key_listener.on_key_press(key)

    def suppress_review_key(event_type, event):
        # 직전 on_press 가 리뷰 결정 키를 처리했으면 그 키 이벤트를 폐기(앱 전달 차단).
        # pynput(darwin)은 on_press 콜백을 먼저 부른 뒤 이 intercept 를 호출하므로
        # 같은 키 이벤트에 대해 결정 처리 → 폐기가 한 번에 일어난다.
        if getattr(app, "_review_suppress", False):
            app._review_suppress = False
            return None
        return event

    listener = keyboard.Listener(
        on_press=on_review_or_hotkey,
        on_release=key_listener.on_key_release,
        darwin_intercept=suppress_review_key,
    )
    listener.start()

    print("Running Qwen Dictation. Dashboard: http://127.0.0.1:5001")
    app.run()


if __name__ == "__main__":
    sys.exit(main())
