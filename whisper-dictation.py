import argparse
import multiprocessing
import os
import re
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
import vocabulary
import dictation_history
import audio_level
import hud_overlay
import hotkeys
import settings_window

try:
    from Foundation import NSOperationQueue, NSThread
except Exception:
    NSOperationQueue = None
    NSThread = None

try:
    from Quartz import (
        CGEventGetFlags,
        kCGEventFlagMaskSecondaryFn,
        kCGEventFlagsChanged,
    )
except Exception:
    CGEventGetFlags = None
    kCGEventFlagMaskSecondaryFn = 1 << 23
    kCGEventFlagsChanged = 12


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

# int16 진폭(최대 32767). 이 값보다 peak 가 작으면 말소리가 없는 버퍼로 보고
# 받아쓰기를 건너뛴다. 무음/작은 잡음(peak 수백 이하) vs 실제 말(peak 1만 이상)
# 사이 마진이 커서 보수적으로 1000 을 쓴다.
SILENCE_PEAK_THRESHOLD = 1000.0
SPEECH_START_PEAK_THRESHOLD = 3500.0
DEFAULT_MIN_VOLUME = 35
STREAM_INTERVAL = 0.8        # 초: 스트리밍 갱신 주기
PAUSE_SILENCE_SEC = 0.8      # 초: 끝이 이만큼 조용하면 쉼 → 확정
MAX_WINDOW_SEC = 12.0        # 초: 창이 이보다 길면 강제 확정(느려짐 방지)
NOISE_FILLER_TEXTS = {"어", "응", "음", "네", "예"}


def audio_peak(audio_path):
    """오디오의 최대 절대 진폭(int16 스케일). 못 읽으면 inf(게이트 안 함)."""
    try:
        data, _ = sf.read(audio_path, dtype="int16")
        if len(data) == 0:
            return 0.0
        return float(np.max(np.abs(np.asarray(data, dtype=np.int32))))
    except Exception:
        return float("inf")


def pcm_peak(audio_bytes):
    """int16 PCM 바이트의 최대 절대 진폭. 비어 있으면 0."""
    if not audio_bytes:
        return 0.0
    samples = np.frombuffer(audio_bytes, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    return float(np.max(np.abs(samples.astype(np.int32))))


def normalize_min_volume(value):
    """User-facing 1..100 sensitivity threshold. Lower catches quieter speech."""
    try:
        value = int(round(float(value)))
    except (TypeError, ValueError):
        value = DEFAULT_MIN_VOLUME
    return max(1, min(100, value))


def volume_peak_thresholds(min_volume):
    """Return (silence_peak, speech_start_peak) scaled from the legacy defaults."""
    scale = normalize_min_volume(min_volume) / float(DEFAULT_MIN_VOLUME)
    return SILENCE_PEAK_THRESHOLD * scale, SPEECH_START_PEAK_THRESHOLD * scale


def find_input_device_index(pa, preferred_name):
    """Resolve a saved input device name. Empty/missing names use system default."""
    if not preferred_name:
        return None
    for index in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(index)
        if info.get("name") == preferred_name and int(info.get("maxInputChannels", 0)) > 0:
            return index
    return None


def trailing_silence(audio_bytes, rate, peak_threshold, secs):
    """오디오 끝쪽 `secs`초가 사실상 무음(peak < threshold)인지. 길이가 모자라면 False."""
    need = int(rate * secs) * 2  # int16 → 바이트 2배
    if len(audio_bytes) < need or need <= 0:
        return False
    tail = np.frombuffer(audio_bytes[-need:], dtype=np.int16)
    if tail.size == 0:
        return False
    return float(np.max(np.abs(tail.astype(np.int32)))) < peak_threshold


def should_commit(window_secs, paused, max_secs):
    """현재 창을 확정할지: 쉬었거나(paused) 창이 너무 길면(max 초과) 확정."""
    return bool(paused or window_secs >= max_secs)


def looks_like_vocab_echo(text, vocab):
    """결과가 등록 단어들로만(2개 이상) 이뤄졌으면 context 환각(echo)으로 본다.

    Qwen 은 음향 증거가 약하면 시스템 프롬프트의 등록 단어를 그대로 뱉는다.
    실제 발화는 등록 안 된 말(조사·서술어 등)을 포함하므로, 토큰이 모두 등록
    단어이고 2개 이상이면 echo 로 판정한다(단어 1개는 실제 발화일 수 있어 제외).
    """
    if not vocab:
        return False
    cleaned = text.replace(",", " ").replace(".", " ").replace("·", " ")
    tokens = [t for t in cleaned.split() if t]
    if len(tokens) < 2:
        return False
    vset = set(vocab)
    return all(t in vset for t in tokens)


def looks_like_repetition_hallucination(text):
    """Reject short repeated filler that Qwen can emit when there is no speech."""
    compact = re.sub(r"[\s,.;!?·]+", "", text or "")
    if not compact:
        return False
    if len(compact) >= 3 and len(set(compact)) == 1:
        return True
    tokens = [t for t in re.split(r"[\s,.;!?·]+", (text or "").strip()) if t]
    return len(tokens) >= 3 and len(set(tokens)) == 1


def looks_like_pause_noise_filler(text):
    """쉼 끝에서 주변 잡음 때문에 자주 생기는 짧은 단독 응답인지."""
    compact = re.sub(r"[\s,.;!?·]+", "", text or "")
    return compact in NOISE_FILLER_TEXTS


def looks_like_punctuation_only(text):
    """내용 없이 구두점만 생성된 환각인지. 실제 문장에 붙은 구두점은 유지한다."""
    compact = re.sub(r"[\s,.;!?·]+", "", text or "")
    return bool(text and not compact)


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


def dispatch_app(app, callback, *args):
    dispatch = getattr(app, "dispatch_to_main", None)
    if dispatch is None:
        return callback(*args)
    return dispatch(callback, *args)



HOTKEY_KEY_NAMES = {
    "alt": keyboard.Key.alt,
    "alt_r": keyboard.Key.alt_r,
    "cmd": keyboard.Key.cmd,
    "cmd_r": keyboard.Key.cmd_r,
    "ctrl": keyboard.Key.ctrl,
    "ctrl_r": keyboard.Key.ctrl_r,
    "shift": keyboard.Key.shift,
    "shift_r": keyboard.Key.shift_r,
    "space": keyboard.Key.space,
    "enter": keyboard.Key.enter,
    "tab": keyboard.Key.tab,
    "esc": keyboard.Key.esc,
    "backspace": keyboard.Key.backspace,
    "delete": keyboard.Key.delete,
    "up": keyboard.Key.up,
    "down": keyboard.Key.down,
    "left": keyboard.Key.left,
    "right": keyboard.Key.right,
    "home": keyboard.Key.home,
    "end": keyboard.Key.end,
    "page_up": keyboard.Key.page_up,
    "page_down": keyboard.Key.page_down,
}
HOTKEY_KEY_NAMES.update({f"f{number}": getattr(keyboard.Key, f"f{number}") for number in range(1, 21)})
HOTKEY_NAME_BY_KEY = {value: name for name, value in HOTKEY_KEY_NAMES.items()}
HOTKEY_FN = "fn"


# 수동 편집으로 치지 않는 토큰: 모디파이어 단독과 Enter.
# (Enter 는 토글 종료 등 기존 동작을 그대로 둔다.)
EDIT_IGNORED_TOKENS = {
    "shift", "shift_r", "ctrl", "ctrl_r", "alt", "alt_r",
    "cmd", "cmd_r", HOTKEY_FN, "enter",
}


def token_from_key(key):
    """pynput key → stored hotkey token. Unknown keys return None."""
    if key == HOTKEY_FN:
        return HOTKEY_FN
    if key in HOTKEY_NAME_BY_KEY:
        return HOTKEY_NAME_BY_KEY[key]
    char = getattr(key, "char", None)
    return str(char).lower() if char and len(str(char)) == 1 else None


def fn_key_transition(event_type, flags, was_pressed):
    """Quartz flagsChanged 이벤트에서 fn 키의 press/release 전이만 추린다."""
    if event_type != kCGEventFlagsChanged:
        return was_pressed, None
    is_pressed = bool(flags & kCGEventFlagMaskSecondaryFn)
    if is_pressed == was_pressed:
        return was_pressed, None
    return is_pressed, "press" if is_pressed else "release"


def validate_hotkey_config(hold_key, toggle_key):
    return hotkeys.validate_hotkey_pair(hold_key, toggle_key)


def type_diff(old_text, new_text, keyboard_controller, allow_empty=False):
    old_text = old_text.strip()
    new_text = new_text.strip()
    if not new_text:
        if allow_empty:
            for _ in range(len(old_text)):
                keyboard_controller.press(keyboard.Key.backspace)
                keyboard_controller.release(keyboard.Key.backspace)
            return ""
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
        self.model_1_7b = None
        self.model_lock = threading.Lock()

    def get_model(self):
        with self.model_lock:
            if self.model_1_7b is None:
                safe_notify("Qwen Dictation", "Loading model", "Qwen3-ASR-1.7B 모델을 불러옵니다.")
                self.model_1_7b = Qwen3ASRModel.from_pretrained(MODEL_1_7B, dtype=self.dtype)
                self.model_1_7b.model.to(self.device)
                self.model_1_7b.device = self.device
            return self.model_1_7b

    def transcribe_file(self, audio_path, language=None):
        # 무음/잡음만 있는 버퍼는 건너뛴다. context(등록 단어)를 주면 모델이
        # 음향 증거가 없을 때 그 단어들을 그대로 환각으로 뱉으므로(echo), 말소리가
        # 없을 땐 아예 받아쓰지 않는다. peak 진폭 기준(짧은 단어도 peak 는 큼).
        silence_threshold, _ = volume_peak_thresholds(
            getattr(self, "min_volume", DEFAULT_MIN_VOLUME)
        )
        if audio_peak(audio_path) < silence_threshold:
            return ""
        model = self.get_model()
        language = normalize_language(language)
        vocab = vocabulary.load_vocabulary()
        context = vocabulary.build_context(vocab)
        results = model.transcribe(audio_path, context=context, language=language)
        if not results:
            return ""
        text = results[0].text.strip()
        # context 환각(등록 단어만 나옴) 의심 시 → context 없이 다시 받아써 실제 들린 것 우선.
        if looks_like_vocab_echo(text, vocab):
            plain = model.transcribe(audio_path, context="", language=language)
            text = plain[0].text.strip() if plain else ""
        return text


class Recorder:
    def __init__(self, transcriber, app):
        self.transcriber = transcriber
        self.app = app
        self.recording = False
        self.audio_frames = []
        self.audio_lock = threading.Lock()
        self.record_thread = None
        self.stream_thread = None
        self.window_start = 0
        self.committed_text = ""
        self.last_typed = ""
        self.finalize_on_stop = True
        # 사용자가 받아쓰기 중 직접 고친 뒤 "지금 입력창이 새 기준"으로 다시 잡으라는
        # 요청 플래그. 리스너 스레드가 세우고 스트리밍 스레드가 틱 시작에서 소비한다.
        self.rebaseline_pending = False
        # 우리가 type_diff 로 타이핑하는 동안 발생하는 합성 키 이벤트를 사용자의 수동
        # 입력으로 오인하지 않도록, 이 시각 전까지는 들어오는 키를 합성으로 간주한다.
        self.self_type_guard_until = 0.0

    def rebaseline(self):
        """입력창 글자에 대한 소유권을 내려놓는다. 다음 발화는 빈 기준에서 시작해
        백스페이스 없이 커서 위치에 새 글자만 덧붙는다(사용자 수정 보존)."""
        self.rebaseline_pending = True

    def start(self, language=None):
        if self.recording:
            return
        self.audio_frames = []
        self.finalize_on_stop = True
        self.rebaseline_pending = False
        self.recording = True
        self.record_thread = threading.Thread(target=self._record_impl, args=(language,), daemon=True)
        self.record_thread.start()
        self.stream_thread = threading.Thread(target=self._stream_loop, args=(language,), daemon=True)
        self.stream_thread.start()

    def stop(self, finalize=True):
        # 녹음 루프(_record_impl)가 self.recording=False 를 보고 스스로 종료/정리한다.
        self.finalize_on_stop = bool(finalize)
        self.recording = False
        audio_level.clear_level()

    def _record_impl(self, language):
        # pyaudio 로 시스템 기본 입력 장치에서 직접 캡처한다. (ffmpeg avfoundation
        # ':default' 는 이 장비에서 'Input/output error' 로 실패해 0프레임이 됐다.)
        frames_per_buffer = 1024
        pa = None
        stream = None
        try:
            pa = pyaudio.PyAudio()
            input_device_index = find_input_device_index(
                pa, getattr(self.app, "input_device", "")
            )
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                input_device_index=input_device_index,
                frames_per_buffer=frames_per_buffer,
            )
        except Exception as exc:
            self.recording = False
            audio_level.clear_level()
            if pa is not None:
                pa.terminate()
            self.app.dispatch_to_main(self.app.handle_recording_error, str(exc))
            return

        try:
            while self.recording:
                try:
                    data = stream.read(frames_per_buffer, exception_on_overflow=False)
                except Exception as exc:
                    print(f"Audio read error: {exc}")
                    self.recording = False
                    self.app.dispatch_to_main(self.app.handle_recording_error, str(exc))
                    break
                with self.audio_lock:
                    self.audio_frames.append(data)
                audio_level.write_level(audio_level.compute_rms(data))
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            pa.terminate()
            audio_level.clear_level()

    def _write_current_audio(self, path):
        with self.audio_lock:
            frames = list(self.audio_frames)
        if not frames:
            return False
        audio_data = np.frombuffer(b"".join(frames), dtype=np.int16)
        audio_data_fp32 = audio_data.astype(np.float32) / 32768.0
        sf.write(path, audio_data_fp32, 16000)
        return True

    def _type(self, old, new):
        return type_diff(old, new, self.transcriber.pykeyboard, allow_empty=True)

    def _transcribe_window(self, window_bytes, language):
        path = "/tmp/qwen_dictation_stream.wav"
        audio = np.frombuffer(window_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        sf.write(path, audio, 16000)
        return self.transcriber.transcribe_file(path, language=language)

    def _stream_tick(self, language, allow_stopped=False):
        # 사용자가 직접 고친 직후라면 기준점을 현재로 리셋한다. 리스너 스레드와의
        # 경합을 피하려 플래그만 받아 스트리밍 스레드인 여기서 실제 상태를 바꾼다.
        if self.rebaseline_pending:
            with self.audio_lock:
                self.window_start = len(self.audio_frames)
            self.committed_text = ""
            self.last_typed = ""
            self.rebaseline_pending = False
        with self.audio_lock:
            window = b"".join(self.audio_frames[self.window_start:])
            frame_count = len(self.audio_frames)
        if not window:
            return
        # 새 구간은 분명한 말소리가 들어오기 전까지 추론하지 않는다. 작은 주변
        # 소리만 계속 쌓이면 Qwen이 "어", "응", "네" 같은 짧은 말을 만들 수 있다.
        silence_threshold, start_threshold = volume_peak_thresholds(
            getattr(self.app, "min_volume", DEFAULT_MIN_VOLUME)
        )
        self.transcriber.min_volume = normalize_min_volume(
            getattr(self.app, "min_volume", DEFAULT_MIN_VOLUME)
        )
        if pcm_peak(window) < start_threshold:
            with self.audio_lock:
                self.window_start = frame_count
            return
        hypo = self._transcribe_window(window, language)
        if not self.recording and not allow_stopped:
            return
        if looks_like_repetition_hallucination(hypo):
            hypo = ""
        if looks_like_punctuation_only(hypo):
            hypo = ""
        paused = trailing_silence(window, 16000, silence_threshold, PAUSE_SILENCE_SEC)
        if paused and looks_like_pause_noise_filler(hypo):
            hypo = ""
        target = self.committed_text + hypo
        # 타이핑 중과 직후 0.2초는 우리가 만든 합성 키 이벤트가 들어오므로, 그 사이
        # 리스너가 키를 사용자 수동 편집으로 오인하지 않도록 가드 시각을 세운다.
        self.self_type_guard_until = time.time() + 30.0
        try:
            self.last_typed = self._type(self.last_typed, target)
        finally:
            self.self_type_guard_until = time.time() + 0.2
        window_secs = len(window) / 2.0 / 16000.0
        if hypo and should_commit(window_secs, paused, MAX_WINDOW_SEC):
            self.committed_text = target
            with self.audio_lock:
                self.window_start = frame_count

    def _stream_loop(self, language):
        self.window_start = 0
        self.committed_text = ""
        self.last_typed = ""
        while self.recording:
            time.sleep(STREAM_INTERVAL)
            try:
                self._stream_tick(language)
            except Exception as exc:
                print(f"Streaming tick error: {exc}")
        # 일반 정지는 남은 말을 한 번 반영한다. Enter 전송으로 멈춘 경우에는
        # 전송 뒤 새 입력창에 늦은 글자가 들어가지 않도록 마지막 틱을 생략한다.
        if self.finalize_on_stop:
            try:
                self._stream_tick(language, allow_stopped=True)
            except Exception as exc:
                print(f"Streaming final tick error: {exc}")
        dictation_history.add_history(self.last_typed)


class MultiHotkeyListener:
    """사용자 지정 단일키 또는 조합키 2개로 실시간 받아쓰기를 구동한다.

    - 오른쪽 Cmd(cmd_r): 홀드 — 누르는 동안 녹음, 떼면 정지.
    - 토글키: 눌러 시작, 다시 눌러 정지. fn도 설정 가능.
    둘 다 streaming: 말하는 대로 입력창에 실시간 타이핑(문맥 보정 포함).
    동시에 하나의 트리거만 활성(active_trigger).
    """

    def __init__(self, app, hold_key="cmd_r", toggle_key="alt_r"):
        self.app = app
        self.hold_key = hotkeys.normalize_hotkey(hold_key)
        self.toggle_key = hotkeys.normalize_hotkey(toggle_key)
        self.hold_parts = hotkeys.hotkey_parts(self.hold_key)
        self.toggle_parts = hotkeys.hotkey_parts(self.toggle_key)
        self.pressed = set()
        self.toggle_latched = False
        self.active_trigger = None  # None | "hold" | "toggle"

    def _begin(self, trigger):
        if self.app.started:
            return
        self.active_trigger = trigger
        dispatch_app(self.app, self.app.start_app, None)

    def _end(self, trigger, finalize=True):
        if self.active_trigger != trigger:
            return
        dispatch_app(self.app, self.app.stop_app, None, finalize)
        self.active_trigger = None

    def _is_manual_edit(self, token):
        """활성 세션 중 이 키가 사용자의 수동 편집인지 판단(단축키/모디파이어 제외)."""
        if token in self.hold_parts or token in self.toggle_parts:
            return False
        if token in EDIT_IGNORED_TOKENS:
            return False
        return True

    def _handle_manual_edit(self):
        mode = getattr(self.app, "edit_interrupt_mode", "continue")
        if mode == "stop":
            # 마지막 틱 없이 종료 — 사용자가 방금 친 글자를 다시 건드리지 않는다.
            trigger = self.active_trigger
            if trigger is not None:
                self._end(trigger, finalize=False)
        else:  # "continue": 수정 보존하고 세션 유지
            recorder = getattr(self.app, "recorder", None)
            if recorder is not None:
                recorder.rebaseline()

    def on_key_press(self, key):
        token = token_from_key(key)
        if token is None:
            return
        if self.active_trigger is not None and self._is_manual_edit(token):
            recorder = getattr(self.app, "recorder", None)
            guard = getattr(recorder, "self_type_guard_until", 0.0) if recorder else 0.0
            if time.time() < guard:
                return  # 우리가 타이핑한 합성 키 이벤트 — 무시
            self._handle_manual_edit()
            return
        self.pressed.add(token)
        hold_matched = self.hold_parts <= self.pressed
        toggle_matched = self.toggle_parts <= self.pressed
        if hold_matched and not self.app.started:
            self._begin("hold")
        elif toggle_matched and not self.toggle_latched:
            self.toggle_latched = True
            if self.active_trigger == "toggle":
                self._end("toggle")
            elif not self.app.started:
                self._begin("toggle")
        elif key == keyboard.Key.enter and self.active_trigger == "toggle":
            # Let Enter keep flowing to the focused app so it sends normally.
            self._end("toggle", finalize=False)

    def on_key_release(self, key):
        token = token_from_key(key)
        if token is None:
            return
        self.pressed.discard(token)
        if not self.toggle_parts <= self.pressed:
            self.toggle_latched = False
        if self.active_trigger == "hold" and not self.hold_parts <= self.pressed:
            self._end("hold")


class StatusBarApp(rumps.App):
    def __init__(self, languages=None, max_time=None):
        _mb = app_paths.resource_path("assets", "menubar.png")
        if os.path.exists(_mb):
            super().__init__("Qwen Dictation", icon=_mb, template=True)
        else:
            super().__init__("Qwen Dictation", "⏯")
        self.languages = languages or ["ko", "en"]
        self.current_language = self.languages[0]
        self.started = False
        self.processing_active = False
        self._global_listener = None
        self.recorder = None
        self.max_time = max_time
        self.timer = None
        self.elapsed_time = 0
        self.start_time = None

        menu = [
            "Start Recording",
            "Stop Recording",
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
        if max_time is not None:
            self.max_time = max(0, float(max_time))

        # Always-running main-thread timer that drives the in-process native
        # overlay. Its callback runs on the rumps/AppKit main thread, so it is
        # the only place allowed to create/mutate the overlay window.
        self._overlay_timer = rumps.Timer(self._tick_overlay, 0.15)
        self._overlay_timer.start()

    def _tick_overlay(self, _):
        try:
            ov = hud_overlay.get_overlay()
            if self.started and self.start_time is not None:
                elapsed = int(time.time() - self.start_time)
                self.elapsed_time = elapsed
                minutes, seconds = divmod(elapsed, 60)
                self.title = f"({minutes:02d}:{seconds:02d}) 🔴"
                ov.update(audio_level.read_level(), elapsed)
                ov.show_status("로컬 받아쓰기 중")
            elif self.processing_active:
                ov.update(0.0, 0)
                ov.show_status("받아쓰기 변환 중")
            else:
                ov.hide()
        except Exception as exc:
            print(f"overlay tick error: {exc}")

    def current_config(self):
        return {
            "language": self.current_language,
            "max_time": self.max_time or 0,
            "input_device": getattr(self, "input_device", ""),
            "hold_key": getattr(self, "hold_key", "cmd_r"),
            "toggle_key": getattr(self, "toggle_key", "alt_r"),
            "min_volume": getattr(self, "min_volume", DEFAULT_MIN_VOLUME),
            "edit_interrupt_mode": getattr(self, "edit_interrupt_mode", "continue"),
        }

    def dispatch_to_main(self, callback, *args, wait=False):
        """Run AppKit/rumps mutations on the main queue."""
        if NSThread is None or NSOperationQueue is None or NSThread.isMainThread():
            return callback(*args)

        done = threading.Event()
        result = {}

        def run():
            try:
                result["value"] = callback(*args)
            except Exception as exc:
                result["error"] = exc
            finally:
                done.set()

        NSOperationQueue.mainQueue().addOperationWithBlock_(run)
        if not wait:
            return None
        done.wait(timeout=5.0)
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def save_settings(self):
        app_config.save_config(self.current_config())

    def _apply_saved_config(self):
        cfg = app_config.load_config()
        self.current_language = cfg["language"]
        self.max_time = cfg["max_time"]
        self.input_device = cfg["input_device"]
        self.hold_key = cfg["hold_key"]
        self.toggle_key = cfg["toggle_key"]
        self.min_volume = normalize_min_volume(cfg.get("min_volume", DEFAULT_MIN_VOLUME))
        mode = cfg.get("edit_interrupt_mode", "continue")
        self.edit_interrupt_mode = mode if mode in ("continue", "stop") else "continue"
        if getattr(self, "recorder", None) is not None:
            self.recorder.transcriber.min_volume = self.min_volume
        self.sync_menu_state()

    def sync_menu_state(self):
        for lang in self.languages:
            self.menu[f"Language: {lang}"].state = int(self.current_language == lang)

    def open_dashboard(self, _):
        settings_window.open_settings("http://127.0.0.1:5001")

    def change_language(self, sender):
        self.current_language = sender.title.replace("Language: ", "")
        self.sync_menu_state()
        self.save_settings()

    @rumps.clicked("Start Recording")
    def start_app(self, _):
        if self.started or self.processing_active:
            return
        print("Listening...")
        self.started = True
        self.menu["Start Recording"].set_callback(None)
        self.menu["Stop Recording"].set_callback(self.stop_app)
        self.recorder.start(self.current_language)
        if self.max_time and self.max_time > 0:
            self.timer = threading.Timer(
                self.max_time,
                lambda: self.dispatch_to_main(self.stop_app, None),
            )
            self.timer.start()
        self.start_time = time.time()
        self.update_title()

    @rumps.clicked("Stop Recording")
    def stop_app(self, _, finalize=True):
        if not self.started:
            return
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        self.title = None
        self.started = False
        self.menu["Stop Recording"].set_callback(None)
        self.menu["Start Recording"].set_callback(self.start_app)
        self.recorder.stop(finalize=finalize)
        print("Stopped.")

    def handle_recording_error(self, message):
        self.started = False
        self.processing_active = False
        self.title = None
        self.menu["Stop Recording"].set_callback(None)
        self.menu["Start Recording"].set_callback(self.start_app)
        safe_notify("Qwen Dictation", "Microphone error", message)

    def set_processing(self, active):
        self.processing_active = bool(active)

    def update_title(self):
        if self.started and self.start_time is not None:
            self.elapsed_time = int(time.time() - self.start_time)
            minutes, seconds = divmod(self.elapsed_time, 60)
            self.title = f"({minutes:02d}:{seconds:02d}) 🔴"

    def toggle(self):
        if self.started:
            self.stop_app(None)
        else:
            self.start_app(None)

    def build_key_listener(self):
        """현재 홀드/토글 설정으로 키 리스너 객체를 만든다."""
        return MultiHotkeyListener(
            self,
            hold_key=getattr(self, "hold_key", "cmd_r"),
            toggle_key=getattr(self, "toggle_key", "alt_r"),
        )

    def apply_hotkey_config(self):
        """현재 설정으로 전역 단축키 리스너를 (재)구성한다. 즉시 적용."""
        old = getattr(self, "_global_listener", None)
        if old is not None:
            try:
                old.stop()
            except Exception:
                pass
        key_listener = self.build_key_listener()
        self._key_listener = key_listener
        fn_pressed = False

        def on_hotkey(key):
            key_listener.on_key_press(key)

        def intercept_fn_key(event_type, event):
            nonlocal fn_pressed
            if CGEventGetFlags is not None:
                fn_pressed, transition = fn_key_transition(
                    event_type, CGEventGetFlags(event), fn_pressed
                )
                if transition == "press":
                    on_hotkey(HOTKEY_FN)
                elif transition == "release":
                    key_listener.on_key_release(HOTKEY_FN)
            return event

        self._global_listener = keyboard.Listener(
            on_press=on_hotkey,
            on_release=key_listener.on_key_release,
            darwin_intercept=intercept_fn_key,
        )
        self._global_listener.start()


def parse_args():
    parser = argparse.ArgumentParser(description="Local Qwen3-ASR dictation app for macOS.")
    parser.add_argument(
        "-l",
        "--language",
        type=str,
        default="ko,en",
        help="Comma-separated language choices. First item is used initially.",
    )
    parser.add_argument("-t", "--max_time", type=float, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    languages = [item.strip() for item in args.language.split(",") if item.strip()]
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device == "mps" else torch.float32
    print(f"Initializing Qwen3-ASR on {device}...")

    app = StatusBarApp(languages=languages, max_time=args.max_time)
    transcriber = SpeechTranscriber(device, dtype)
    recorder = Recorder(transcriber, app)
    app.recorder = recorder

    # 모델을 백그라운드에서 미리 올려둔다(앱 켤 때 ~6~7초 cold load 를 첫 받아쓰기
    # 시점이 아니라 시작 시점에 숨긴다 → 첫 받아쓰기도 바로 빠르게).
    def _warmup_model():
        try:
            transcriber.get_model()
            print("Model preloaded (1.7b).")
        except Exception as exc:
            print(f"Model preload error: {exc}")

    threading.Thread(target=_warmup_model, daemon=True).start()

    dashboard.start_server(app)
    app.apply_hotkey_config()

    print("Running Qwen Dictation. Dashboard: http://127.0.0.1:5001")
    app.run()


if __name__ == "__main__":
    # PyInstaller's runtime hook uses this to divert resource-tracker and
    # worker subprocesses before they enter the app CLI parser.
    multiprocessing.freeze_support()
    sys.exit(main())
