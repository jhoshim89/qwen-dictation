import argparse
import collections
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
import term_correct
import dictation_history
import audio_level
import hud_overlay
import hotkeys
import settings_window
import text_normalize

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
        CGEventCreateKeyboardEvent,
        CGEventKeyboardSetUnicodeString,
        CGEventPost,
        kCGHIDEventTap,
    )
except Exception:
    CGEventGetFlags = None
    kCGEventFlagMaskSecondaryFn = 1 << 23
    kCGEventFlagsChanged = 12
    CGEventCreateKeyboardEvent = None
    CGEventKeyboardSetUnicodeString = None
    CGEventPost = None
    kCGHIDEventTap = None


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
# 마이크 한 번 읽을 때 샘플 수(~64ms @16kHz). 마이크는 앱 시작부터 계속 열어두고
# 읽어, 키 누르는 순간 바로 잡히게 한다(누를 때마다 새로 여는 ~1초 지연 제거).
FRAMES_PER_BUFFER = 1024
# 키 누르기 직전 이만큼을 미리 들고 있다가 받아쓰기에 포함한다(누르자마자, 혹은
# 살짝 먼저 말해도 첫 단어가 안 잘림).
PREROLL_SEC = 0.5
PREROLL_CHUNKS = max(1, round(PREROLL_SEC * 16000 / FRAMES_PER_BUFFER))
# 이 맥에서 한 번 받아쓰는 데 약 0.1초밖에 안 걸린다(길이 1~8초 측정, mps). 그래서
# 끝의 기다림은 모델 속도가 아니라 '확인 간격'이 좌우한다. 간격을 짧게 둬 말끝이 빨리
# 들어오게 한다. (일반 권장값 0.8초는 모델이 느릴 때 얘기라 우리엔 과하게 보수적)
STREAM_INTERVAL = 0.25       # 초: 스트리밍 갱신 주기(추론 ~0.1초라 자주 확인해도 안 밀림 → 마지막 말이 빨리 뜸)
PAUSE_SILENCE_SEC = 0.3      # 초: 끝이 이만큼 조용하면 쉼 → 확정(단어 사이 멈춤과 구분되는 바닥값)
# 매 틱마다 '확정 이후의 창 전체'를 다시 받아쓴다. 보통은 쉼(PAUSE_SILENCE_SEC)에서 먼저
# 확정되므로 이 상한은 거의 안 걸린다. Whisper 계열 30초 한계보다 한참 아래로 두는 안전망.
MAX_WINDOW_SEC = 12.0        # 초: 창이 이보다 길면 강제 확정(드물게 걸리는 안전망)
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

    Qwen 은 음향 증거가 약하면 시스템 프롬프트의 등록 단어를 그대로 뱉는다. 여러
    단어로 된 등록어('corneal ulcer')도 잡으려고 토큰이 아니라 '구(phrase)' 단위로,
    긴 것부터 지워 나간다. 등록어 2개 이상이 출력의 사실상 전부를 차지하면 echo.
    """
    if not vocab or not text:
        return False
    norm = " " + re.sub(r"[\s,.;!?·]+", " ", text).strip().lower() + " "
    phrases = sorted(
        {str(v).strip().lower() for v in vocab if str(v).strip()},
        key=len,
        reverse=True,
    )
    matched = 0
    for phrase in phrases:
        token = " " + phrase + " "
        while token in norm:
            norm = norm.replace(token, "  ", 1)
            matched += 1
    leftover = re.sub(r"\s+", "", norm)
    return matched >= 2 and leftover == ""


def vocab_terms_in_text(text, vocab):
    """text 에 (조사·구두점 무시) 등장하는 등록 단어 목록 — vocab 등록 순서로.

    '녹내장이', '오늘 환자 녹내장 봤어' 처럼 실제 말에 조사가 붙거나 섞여 끼어든
    경우까지 잡으려고 공백/구두점을 없앤 부분문자열로 본다. 단독 echo(1개)와
    혼합 leakage 를 함께 잡아, 편향 끈 결과와 대조할 후보를 고른다.
    """
    if not vocab or not text:
        return []
    norm = re.sub(r"[\s,.;!?·]+", "", text).lower()
    found = []
    seen = set()
    for v in vocab:
        phrase = str(v).strip().lower().replace(" ", "")
        if phrase and phrase in norm and phrase not in seen:
            seen.add(phrase)
            found.append(phrase)
    return found


DOMAIN_ECHO_PROBE_LEN = 10


def looks_like_domain_echo(text, domain):
    """결과에 분야 머리말(domain)이 새어 들어온 context 환각(echo)인지 본다.

    `context` 는 모델의 system 지시문으로 들어가는데, 완결된 긴 분야 문장은 모델이
    '받아쓸 내용'으로 착각해 출력에 흘린다(leakage). 두 형태를 잡는다:
      1) 결과가 분야 문장의 앞부분/전체  — 약하거나 짧은 첫 조각의 순수 echo
      2) 분야 문장의 식별 가능한 앞 조각이 결과 어딘가에 끼어듦 — 실제 단어와 섞인 leakage
         (예: "녹내장 수의안과 진료와 소프트웨어 개발 …")
    공백·구두점·대시(—,–,-)를 무시하고 비교한다. domain 이 비었거나 text 가 비면 False.
    """
    domain = str(domain).strip()
    text = str(text).strip()
    if not domain or not text:
        return False
    strip_re = r"[\s,.;!?·\-—–]+"
    norm_text = re.sub(strip_re, "", text).lower()
    norm_domain = re.sub(strip_re, "", domain).lower()
    if not norm_text:
        return False
    if norm_domain.startswith(norm_text):
        return True
    probe = norm_domain[:DOMAIN_ECHO_PROBE_LEN] if len(norm_domain) >= DOMAIN_ECHO_PROBE_LEN else norm_domain
    return bool(probe) and probe in norm_text


def looks_like_context_label_echo(text):
    """출력에 context 머리표('전문 용어')가 들어오면 통째 echo 로 본다.

    build_context 는 등록 단어를 `전문 용어: a, b` 로 라벨링해 모델에 넣는다. 근거가
    약한 첫 구간에서 모델은 이 라벨을 단어째(때로는 vocab 에 없는 분야 용어를 지어내
    붙여서) 그대로 뱉는다. 머리표는 사용자가 말하는 내용이 아니므로, 존재만으로 echo
    로 판정한다 — 단어 echo·분야 echo 가드가 vocab/domain 매칭에 실패하는 경우까지 잡는다.
    """
    return bool(text) and vocabulary.CONTEXT_TERM_LABEL in text


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


def unicode_type(text, _post=None):
    """Insert `text` as literal Unicode via CGEvents (keycode 0 + Unicode string).

    Posting on keycode 0 with the Unicode string set makes macOS insert the
    characters literally, bypassing the active keyboard layout and IME. A Korean
    input source therefore can't remap Latin letters to Hangul, so English
    dictation lands as English. `_post` is injectable for tests.
    """
    post = _post or CGEventPost
    for ch in text:
        down = CGEventCreateKeyboardEvent(None, 0, True)
        CGEventKeyboardSetUnicodeString(down, 1, ch)
        post(kCGHIDEventTap, down)
        up = CGEventCreateKeyboardEvent(None, 0, False)
        CGEventKeyboardSetUnicodeString(up, 1, ch)
        post(kCGHIDEventTap, up)


def type_diff(old_text, new_text, keyboard_controller, allow_empty=False, insert=None):
    # `insert(text)` performs the actual character insertion. Default is the
    # pynput controller's keystroke typing, but the streaming path injects an
    # IME-immune Unicode inserter so Latin text isn't remapped to Hangul.
    if insert is None:
        insert = keyboard_controller.type
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
        insert(new_text)
        return new_text
    if new_text.startswith(old_text):
        diff = new_text[len(old_text):]
        if diff:
            insert(diff)
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
        insert(diff)
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
        # 무음/잡음만 있는 버퍼는 건너뛴다. 용어/분야는 모델에 주지 않는다(context 가
        # 출력에 새는 echo 를 원천 차단). 등록 용어 반영은 받아쓴 뒤 term_correct 가 한다.
        silence_threshold, _ = volume_peak_thresholds(
            getattr(self, "min_volume", DEFAULT_MIN_VOLUME)
        )
        if audio_peak(audio_path) < silence_threshold:
            return ""
        model = self.get_model()
        language = normalize_language(language)
        results = model.transcribe(audio_path, context="", language=language)
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
        self.stream_thread = None
        # 항상 열려 도는 마이크 캡처 스레드와, 그 캡처가 쓰는 PortAudio 스트림.
        self._capture_on = False
        self._capture_thread = None
        self._pa = None
        self._stream = None
        self._open_device = None
        self._capture_error_notified = False
        # 키 누르기 직전 오디오를 들고 있는 롤링 버퍼(받아쓰기 시작 시 앞에 붙인다).
        self._preroll = collections.deque(maxlen=PREROLL_CHUNKS)
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
        # 홀드 키를 떼서 정상 종료할 때만, 마지막 글자 입력 뒤 Enter 를 보낼지.
        self.send_enter_on_stop = False
        # 스트리밍 루프의 주기 대기를 즉시 깨우는 정지 신호. 키를 떼면 set 되어
        # 다음 확인 주기를 기다리지 않고 곧장 마지막 틱(+Enter)으로 넘어간다.
        self._wake = threading.Event()

    def rebaseline(self):
        """입력창 글자에 대한 소유권을 내려놓는다. 다음 발화는 빈 기준에서 시작해
        백스페이스 없이 커서 위치에 새 글자만 덧붙는다(사용자 수정 보존)."""
        self.rebaseline_pending = True

    def start(self, language=None):
        if self.recording:
            return
        self.finalize_on_stop = True
        self.send_enter_on_stop = False
        self.rebaseline_pending = False
        self._wake.clear()
        # 마이크는 이미 계속 열려 있으니 여는 지연이 없다. 직전 0.5초(preroll)를 앞에
        # 붙여, 키 누르자마자/살짝 먼저 말해도 첫 단어가 잡히게 한다.
        with self.audio_lock:
            self.audio_frames = list(self._preroll)
        self.recording = True
        # 캡처가 아직 안 돌고 있으면(안전망) 지금 띄운다.
        self.start_capture()
        self.stream_thread = threading.Thread(target=self._stream_loop, args=(language,), daemon=True)
        self.stream_thread.start()

    def stop(self, finalize=True, send_enter=False):
        # recording=False 면 캡처 스레드는 계속 돌되 audio_frames 에 더는 안 쌓고
        # preroll 만 갱신한다(마이크는 계속 열린 채 다음 시작을 즉시 받는다).
        self.finalize_on_stop = bool(finalize)
        # 홀드 해제로 정상 종료할 때만 마지막 글자 입력 뒤 Enter 를 보낸다.
        self.send_enter_on_stop = bool(send_enter and finalize)
        self.recording = False
        # 스트리밍 루프가 주기 대기 중이면 즉시 깨워 마지막 처리를 바로 시작한다.
        self._wake.set()
        audio_level.clear_level()

    def start_capture(self):
        """앱 시작 시 마이크를 미리 열어 계속 읽어둔다(키 누르면 즉시 잡히도록).

        한 번만 띄우면 되고, 이후 떼고/다시 누르는 동안 스트림은 계속 열려 있다.
        """
        if self._capture_on:
            return
        self._capture_on = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def stop_capture(self):
        """마이크 캡처를 멈춘다(앱 종료 정리용). 루프가 스스로 스트림을 닫는다."""
        self._capture_on = False

    def _open_stream(self):
        # pyaudio 로 시스템 기본 입력 장치에서 직접 캡처한다. (ffmpeg avfoundation
        # ':default' 는 이 장비에서 'Input/output error' 로 실패해 0프레임이 됐다.)
        self._pa = pyaudio.PyAudio()
        device = getattr(self.app, "input_device", "")
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            input_device_index=find_input_device_index(self._pa, device),
            frames_per_buffer=FRAMES_PER_BUFFER,
        )
        self._open_device = device

    def _close_stream(self):
        try:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
        except Exception:
            pass
        try:
            if self._pa is not None:
                self._pa.terminate()
        except Exception:
            pass
        self._stream = None
        self._pa = None
        self._open_device = None

    def _capture_loop(self):
        try:
            while self._capture_on:
                # 스트림이 없거나 대시보드에서 마이크가 바뀌었으면 (재)연다.
                if self._stream is None or self._open_device != getattr(self.app, "input_device", ""):
                    self._close_stream()
                    try:
                        self._open_stream()
                        self._capture_error_notified = False
                    except Exception as exc:
                        if not self._capture_error_notified:
                            self._capture_error_notified = True
                            self.app.dispatch_to_main(self.app.handle_recording_error, str(exc))
                        time.sleep(0.5)
                        continue
                try:
                    data = self._stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)
                except Exception as exc:
                    print(f"Audio read error: {exc}")
                    self._close_stream()
                    time.sleep(0.2)
                    continue
                with self.audio_lock:
                    self._preroll.append(data)
                    if self.recording:
                        self.audio_frames.append(data)
                if self.recording:
                    audio_level.write_level(audio_level.compute_rms(data))
        finally:
            self._close_stream()
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
        # Insert via IME-immune Unicode CGEvents so Latin text isn't remapped to
        # Hangul under a Korean input source; fall back to keystrokes if Quartz
        # CGEvents are unavailable. Backspaces stay as keycodes either way.
        inserter = unicode_type if CGEventCreateKeyboardEvent is not None else None
        return type_diff(old, new, self.transcriber.pykeyboard,
                         allow_empty=True, insert=inserter)

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
        self.transcriber.domain_context = getattr(self.app, "domain_context", "")
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
        # 등록 용어로 사후 교정한다(모델엔 용어를 안 줬으므로 여기서만 반영).
        hypo = term_correct.correct_terms(hypo, getattr(self, "session_vocab", None) or [])
        # 단위가 붙은 한국어 수사만 아라비아 숫자로 바꾼다('삼 밀리'->3밀리). 변환은
        # idempotent 라 확정 텍스트에 다시 적용해도 안전하다.
        target = text_normalize.normalize_numbers(self.committed_text + hypo)
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

    def _send_enter(self, settle=0.03):
        """마지막 글자까지 입력된 뒤 Enter 를 보낸다(홀드 떼면 자동 전송).

        settle: 직전에 새로 친 글자가 OS 에 반영될 시간을 주는 짧은 대기. 마지막
        틱에서 새로 친 글자가 없으면(이미 말 끝나 쉰 경우) 0 으로 두고 곧장 보낸다.
        """
        # 합성 Enter 가 수동 편집으로 오인되지 않도록 가드 시각을 잠깐 세운다.
        self.self_type_guard_until = time.time() + 0.5
        try:
            if settle > 0:
                time.sleep(settle)  # 직전 타이핑 합성 이벤트 flush
            kb = self.transcriber.pykeyboard
            kb.press(keyboard.Key.enter)
            kb.release(keyboard.Key.enter)
        except Exception as exc:
            print(f"send enter error: {exc}")

    def _stream_loop(self, language):
        self.window_start = 0
        self.committed_text = ""
        self.last_typed = ""
        self.session_vocab = vocabulary.load_vocabulary()
        while self.recording:
            # 주기마다 한 번씩 틱. 단, 도중에 정지 신호가 오면 즉시 깨어나
            # 남은 대기 없이 곧장 마지막 틱으로 넘어간다(키 떼고 Enter 지연 최소화).
            if self._wake.wait(STREAM_INTERVAL):
                break
            try:
                self._stream_tick(language)
            except Exception as exc:
                print(f"Streaming tick error: {exc}")
        # 일반 정지는 남은 말을 한 번 반영한다. Enter 전송으로 멈춘 경우에는
        # 전송 뒤 새 입력창에 늦은 글자가 들어가지 않도록 마지막 틱을 생략한다.
        typed_before = self.last_typed
        if self.finalize_on_stop:
            try:
                self._stream_tick(language, allow_stopped=True)
            except Exception as exc:
                print(f"Streaming final tick error: {exc}")
        # Enter 를 먼저 보내고(사용자가 체감하는 지연), 기록 저장은 그 뒤로 미룬다.
        # 마지막 틱에서 새로 친 글자가 있으면 짧은 반영 대기를, 없으면 곧장 보낸다.
        if getattr(self, "send_enter_on_stop", False):
            self._send_enter(settle=0.03 if self.last_typed != typed_before else 0.0)
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
        # 홀드 키를 떼서 정상 종료할 때만, 설정이 켜져 있으면 마지막 글자 입력 뒤
        # Enter 를 보낸다. 토글 종료·수동 편집 종료(finalize=False)에는 보내지 않는다.
        send_enter = (
            trigger == "hold"
            and finalize
            and bool(getattr(self.app, "hold_send_enter", False))
        )
        dispatch_app(self.app, self.app.stop_app, None, finalize, send_enter)
        self.active_trigger = None

    def _is_manual_edit(self, token):
        """활성 세션 중 이 키가 사용자의 수동 편집인지 판단(단축키/모디파이어 제외)."""
        if token in self.hold_parts or token in self.toggle_parts:
            return False
        if token in EDIT_IGNORED_TOKENS:
            return False
        return True

    def _handle_manual_edit(self):
        mode = getattr(self.app, "edit_interrupt_mode", "stop")
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
            desired = (
                getattr(self, "hud_mode", "pill"),
                getattr(self, "hud_pin_x", None),
                getattr(self, "hud_pin_y", None),
            )
            if desired != getattr(self, "_applied_hud", None):
                ov.set_mode(desired[0], (desired[1], desired[2]))
                self._applied_hud = desired
            mode = desired[0]

            if self.started and self.start_time is not None:
                elapsed = int(time.time() - self.start_time)
                self.elapsed_time = elapsed
                minutes, seconds = divmod(elapsed, 60)
                self.title = f"({minutes:02d}:{seconds:02d}) 🔴"
                ov.update(audio_level.read_level(), elapsed)
                ov.set_processing(False)
                ov.show_status("듣는 중")
                if mode == "pinned":
                    origin = ov.current_origin()
                    if origin and (origin[0], origin[1]) != (self.hud_pin_x, self.hud_pin_y):
                        self.hud_pin_x, self.hud_pin_y = origin
                        self.save_settings()
                        self._applied_hud = (mode, origin[0], origin[1])
            elif self.processing_active:
                ov.update(0.0, 0)
                ov.set_processing(True)
                ov.show_status("변환 중")
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
            "edit_interrupt_mode": getattr(self, "edit_interrupt_mode", "stop"),
            "hold_send_enter": getattr(self, "hold_send_enter", True),
            "domain_context": getattr(self, "domain_context", ""),
            "hud_mode": getattr(self, "hud_mode", "pill"),
            "hud_pin_x": getattr(self, "hud_pin_x", None),
            "hud_pin_y": getattr(self, "hud_pin_y", None),
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
        mode = cfg.get("edit_interrupt_mode", "stop")
        self.edit_interrupt_mode = mode if mode in ("continue", "stop") else "stop"
        self.hold_send_enter = bool(cfg.get("hold_send_enter", True))
        self.domain_context = str(cfg.get("domain_context", "") or "")
        self.hud_mode = hud_overlay.normalize_hud_mode(cfg.get("hud_mode", "pill"))
        self.hud_pin_x = cfg.get("hud_pin_x")
        self.hud_pin_y = cfg.get("hud_pin_y")
        if getattr(self, "recorder", None) is not None:
            self.recorder.transcriber.min_volume = self.min_volume
            self.recorder.transcriber.domain_context = self.domain_context
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
    def stop_app(self, _, finalize=True, send_enter=False):
        if not self.started:
            return
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        self.title = None
        self.started = False
        self.menu["Stop Recording"].set_callback(None)
        self.menu["Start Recording"].set_callback(self.start_app)
        self.recorder.stop(finalize=finalize, send_enter=send_enter)
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

    # 마이크도 시작 시점에 미리 열어 계속 읽어둔다. 키 누르는 순간 바로 잡혀,
    # 홀드로 누르자마자 말해도 첫 단어가 잘리지 않는다(여는 ~1초 지연 제거).
    recorder.start_capture()

    dashboard.start_server(app)
    app.apply_hotkey_config()

    print("Running Qwen Dictation. Dashboard: http://127.0.0.1:5001")
    app.run()


if __name__ == "__main__":
    # PyInstaller's runtime hook uses this to divert resource-tracker and
    # worker subprocesses before they enter the app CLI parser.
    multiprocessing.freeze_support()
    sys.exit(main())
