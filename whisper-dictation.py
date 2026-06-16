import argparse
import collections
import json
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
import asr_engines
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
        CGEventSetFlags,
        kCGHIDEventTap,
    )
except Exception:
    CGEventGetFlags = None
    kCGEventFlagMaskSecondaryFn = 1 << 23
    kCGEventFlagsChanged = 12
    CGEventCreateKeyboardEvent = None
    CGEventKeyboardSetUnicodeString = None
    CGEventPost = None
    CGEventSetFlags = None
    kCGHIDEventTap = None


def _safe_keyboard_listener_class():
    """Caps Lock(한/영) 입력소스 전환 충돌을 막은 키 리스너 클래스를 만든다.

    pynput 의 키 리스너는 NSSystemDefined(미디어/시스템 정의) 이벤트를
    NSEvent.eventWithCGEvent_ 로 변환한다. 그런데 Caps Lock 을 한/영 토글로 쓰는
    환경에서 그 변환이 백그라운드 탭 스레드에서 TSM 입력소스 전환을 호출하고, TSM 이
    메인 디스패치 큐를 강제(assert)해 앱이 EXC_BREAKPOINT(SIGTRAP)로 즉사한다
    (크래시 리포트로 확인). 이 앱은 미디어 키를 단축키로 쓰지 않으므로, 그 이벤트
    종류를 리스너 mask 에서 빼 변환 자체가 일어나지 않게 한다.
    """
    base = keyboard.Listener
    try:
        from pynput.keyboard._darwin import CGEventMaskBit, NSSystemDefined
    except Exception:
        return base  # 비-macOS 또는 pynput 내부 변경 시: 원본 그대로 사용

    class _SafeKeyboardListener(base):
        _EVENTS = base._EVENTS & ~CGEventMaskBit(NSSystemDefined)

    return _SafeKeyboardListener


SafeKeyboardListener = _safe_keyboard_listener_class()


MODEL_1_7B = asr_engines.QWEN_MODEL_ID
NEMOTRON_MLX_MODEL = asr_engines.NEMOTRON_MLX_MODEL_ID
SHERPA_ONNX_KO_MODEL = asr_engines.SHERPA_ONNX_KO_MODEL_ID
GOOGLE_STT_CREDENTIAL_ENV = "QWEN_GOOGLE_STT_CREDENTIALS"
GOOGLE_STT_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_GOOGLE_AUTHORIZED_USER_CREDENTIALS = None
_GOOGLE_SERVICE_ACCOUNT_CREDENTIALS = None

# int16 진폭(최대 32767). 이 값보다 peak 가 작으면 말소리가 없는 버퍼로 보고
# 받아쓰기를 건너뛴다. 무음/작은 잡음(peak 수백 이하) vs 실제 말(peak 1만 이상)
# 사이 마진이 커서 보수적으로 1000 을 쓴다.
SILENCE_PEAK_THRESHOLD = 1000.0
SPEECH_START_PEAK_THRESHOLD = 3500.0
DEFAULT_MIN_VOLUME = 35
# 마이크 한 번 읽을 때 샘플 수(~64ms @16kHz). 마이크는 앱 시작부터 계속 열어두고
# 읽어, 키 누르는 순간 바로 잡히게 한다(누를 때마다 새로 여는 ~1초 지연 제거).
FRAMES_PER_BUFFER = 1024
# 키 누르기 직전 이만큼을 미리 들고 있다가 받아쓰기에 포함한다. 토글을 누른 직후
# 바로 말하는 습관에서는 첫 음절이 버튼 타이밍보다 살짝 앞서거나, 시작 직후 작게
# 들어오는 경우가 있어 1초 정도를 붙여 첫 단어가 잘리지 않게 한다.
PREROLL_SEC = 1.0
PREROLL_CHUNKS = max(1, round(PREROLL_SEC * 16000 / FRAMES_PER_BUFFER))
SPEECH_START_LOOKBACK_SEC = 0.8
SPEECH_START_LOOKBACK_CHUNKS = max(1, round(SPEECH_START_LOOKBACK_SEC * 16000 / FRAMES_PER_BUFFER))
# 이 맥에서 한 번 받아쓰는 데 약 0.1초밖에 안 걸린다(길이 1~8초 측정, mps). 그래서
# 끝의 기다림은 모델 속도가 아니라 '확인 간격'이 좌우한다. 간격을 짧게 둬 말끝이 빨리
# 들어오게 한다. (일반 권장값 0.8초는 모델이 느릴 때 얘기라 우리엔 과하게 보수적)
STREAM_INTERVAL = 0.25       # 초: 스트리밍 갱신 주기(추론 ~0.1초라 자주 확인해도 안 밀림 → 마지막 말이 빨리 뜸)
PAUSE_SILENCE_SEC = 0.3      # 초: 끝이 이만큼 조용하면 쉼 → 확정(단어 사이 멈춤과 구분되는 바닥값)
# 배경음 때문에 쉼 판정이 계속 실패해도, 같은 인식 결과가 연속으로 고정되면 커밋한다.
# 3틱은 현재 STREAM_INTERVAL 기준 약 0.75초다.
STABLE_COMMIT_TICKS = 3
# 매 틱마다 '확정 이후의 창 전체'를 다시 받아쓴다. 보통은 쉼(PAUSE_SILENCE_SEC)에서 먼저
# 확정되므로 이 상한은 거의 안 걸린다. Whisper 계열 30초 한계보다 한참 아래로 두는 안전망.
MAX_WINDOW_SEC = 12.0        # 초: 창이 이보다 길면 강제 확정(드물게 걸리는 안전망)
# 확정 시점 편향(context)을 적용할 최소 창 길이(초). 이보다 짧은 확정 창은 음향 증거가
# 약해 누출 위험이 커지므로 편향하지 않고 무편향 결과를 그대로 쓴다.
BIAS_MIN_WINDOW_SEC = 1.0
# pynput/Quartz 합성 키 이벤트가 type_diff 반환 뒤 늦게 도착할 수 있다. 이 시간 안에
# 들어온 키는 사용자의 수동 편집으로 보지 않아 세션이 중간에 끊기는 것을 막는다.
SELF_TYPE_GUARD_SETTLE_SEC = 1.25
MAC_BACKSPACE_KEYCODE = 51
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


# 한글(자모 포함)과 라틴 문자(악센트 포함) — '허용' 글자. 사용자 콘텐츠는 한국어
# 아니면 영어뿐이라, 짧은 라이브 창에서 auto 감지가 흔들려 중국어·일본어·러시아어
# 등으로 새는 경우만 골라낸다.
_KO_EN_LETTER_RE = re.compile(
    "[A-Za-z"            # 영어(라틴 기본)
    "À-ɏ"      # 라틴 악센트(café 등)
    "ᄀ-ᇿ"      # 한글 자모
    "㄰-㆏"      # 한글 호환 자모
    "가-힣"      # 한글 음절
    "ﾠ-ￜ]"     # 반각 한글
)
_ANY_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def looks_like_foreign_language(text):
    """한국어(한글)도 영어(라틴)도 아닌 언어로 받아써졌는지. 글자가 하나라도 있고
    그 글자들 중 한글·라틴이 하나도 없으면(전부 외국 문자면) True. 숫자·기호만
    있거나 한글/영어가 한 글자라도 섞이면 False — 진짜 발화를 지우지 않으려는
    보수적 기준이다(드물게 한자가 섞인 한국어 등은 일부러 건드리지 않는다)."""
    if not text:
        return False
    if _KO_EN_LETTER_RE.search(text):
        return False
    return bool(_ANY_LETTER_RE.search(text))


def agreed_word_prefix(prev, curr):
    """직전 결과(prev)와 현재 결과(curr)가 앞에서부터 연속으로 같은 '단어'만 이어 돌려준다.

    LocalAgreement-2: 두 번 연속 같게 들린 앞부분만 확정해 화면에 보여주면, 진행 중에
    뒷말 때문에 앞말이 바뀌는 흔들림('왔다갔다')이 사라진다. 부분문자열이 아니라 공백
    기준 단어 단위로 비교한다('안녕'≠'안녕하세요').
    """
    pw, cw = (prev or "").split(), (curr or "").split()
    n = 0
    while n < len(pw) and n < len(cw) and pw[n] == cw[n]:
        n += 1
    return " ".join(cw[:n])


def safe_notify(title, subtitle, message):
    try:
        rumps.notification(title, subtitle, message)
    except Exception as exc:
        print(f"Notification error (non-fatal): {exc}")


def normalize_language(language):
    return asr_engines.normalize_qwen_language(language)


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
        if CGEventSetFlags is not None:
            CGEventSetFlags(down, 0)
        CGEventKeyboardSetUnicodeString(down, 1, ch)
        post(kCGHIDEventTap, down)
        up = CGEventCreateKeyboardEvent(None, 0, False)
        if CGEventSetFlags is not None:
            CGEventSetFlags(up, 0)
        CGEventKeyboardSetUnicodeString(up, 1, ch)
        post(kCGHIDEventTap, up)


def plain_backspace(_post=None):
    """Send a plain Backspace key event with modifier flags cleared."""
    post = _post or CGEventPost
    down = CGEventCreateKeyboardEvent(None, MAC_BACKSPACE_KEYCODE, True)
    if CGEventSetFlags is not None:
        CGEventSetFlags(down, 0)
    post(kCGHIDEventTap, down)
    up = CGEventCreateKeyboardEvent(None, MAC_BACKSPACE_KEYCODE, False)
    if CGEventSetFlags is not None:
        CGEventSetFlags(up, 0)
    post(kCGHIDEventTap, up)


def type_diff(
    old_text,
    new_text,
    keyboard_controller,
    allow_empty=False,
    insert=None,
    append_only=False,
    delete_backward=None,
):
    # `insert(text)` performs the actual character insertion. Default is the
    # pynput controller's keystroke typing, but the streaming path injects an
    # IME-immune Unicode inserter so Latin text isn't remapped to Hangul.
    if insert is None:
        insert = keyboard_controller.type
    if delete_backward is None:
        def delete_backward():
            keyboard_controller.press(keyboard.Key.backspace)
            keyboard_controller.release(keyboard.Key.backspace)
    old_text = old_text.strip()
    new_text = new_text.strip()
    if not new_text:
        if append_only:
            return old_text
        if allow_empty:
            for _ in range(len(old_text)):
                delete_backward()
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

    if append_only:
        return old_text

    common_prefix = os.path.commonprefix([old_text, new_text])
    backspaces = len(old_text) - len(common_prefix)
    for _ in range(backspaces):
        delete_backward()
        time.sleep(0.001)
    diff = new_text[len(common_prefix):]
    if diff:
        insert(diff)
        return new_text
    return old_text


class SpeechTranscriber:
    def __init__(self, device, dtype, asr_engine=asr_engines.DEFAULT_ASR_ENGINE):
        self.device = device
        self.dtype = dtype
        self.pykeyboard = keyboard.Controller()
        self.asr_engine = asr_engines.normalize_asr_engine(asr_engine)
        self.model_1_7b = None
        self.nemotron_mlx_model = None
        self.google_speech_client = None
        self.sherpa_onnx_recognizer = None
        self.model_lock = threading.Lock()
        # 모델을 실제로 올리는 중인지(HUD 가 '불러오는 중'을 보여줄 신호). 성공/실패 모두
        # finally 에서 내려, 로드 실패 시 표시가 영원히 남지 않게 한다.
        self.loading = False

    def set_engine(self, asr_engine):
        self.asr_engine = asr_engines.normalize_asr_engine(asr_engine)

    def current_engine_label(self):
        return asr_engines.asr_engine_label(self.asr_engine)

    def get_model(self):
        with self.model_lock:
            if self.model_1_7b is None:
                self.loading = True
                try:
                    safe_notify("Qwen Dictation", "Loading model", "Qwen3-ASR-1.7B 모델을 불러옵니다.")
                    self.model_1_7b = Qwen3ASRModel.from_pretrained(MODEL_1_7B, dtype=self.dtype)
                    self.model_1_7b.model.to(self.device)
                    self.model_1_7b.device = self.device
                finally:
                    self.loading = False
            return self.model_1_7b

    def get_nemotron_model(self):
        with self.model_lock:
            if self.nemotron_mlx_model is None:
                self.loading = True
                try:
                    safe_notify(
                        "Qwen Dictation",
                        "Loading model",
                        "Nemotron 3.5 ASR MLX 모델을 불러옵니다.",
                    )
                    try:
                        from mlx_audio.stt import load as load_stt_model
                    except Exception as exc:
                        raise RuntimeError(
                            "Nemotron MLX 엔진을 쓰려면 mlx-audio optional runtime이 필요합니다. "
                            "README의 Nemotron 설치 안내를 먼저 실행하세요."
                        ) from exc

                    self.nemotron_mlx_model = load_stt_model(NEMOTRON_MLX_MODEL)
                finally:
                    self.loading = False
            return self.nemotron_mlx_model

    def _load_google_speech_module(self):
        try:
            from google.cloud import speech
        except Exception as exc:
            raise RuntimeError(
                "Google STT 엔진을 쓰려면 google-cloud-speech 패키지가 필요합니다. "
                "`./venv/bin/python -m pip install google-cloud-speech` 후 다시 시도하세요."
            ) from exc
        return speech

    def _google_stt_credential_candidates(self):
        explicit = os.environ.get(GOOGLE_STT_CREDENTIAL_ENV, "").strip()
        if explicit:
            return [(os.path.expanduser(explicit), True)]
        return [
            (os.path.expanduser("~/.config/mcp-gsheets/token.json"), False),
        ]

    def _google_stt_credentials_from_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            raise RuntimeError(f"Google STT credential 파일을 읽을 수 없습니다: {path}") from exc

        if data.get("type") == "service_account":
            global _GOOGLE_SERVICE_ACCOUNT_CREDENTIALS
            if _GOOGLE_SERVICE_ACCOUNT_CREDENTIALS is None:
                from google.oauth2 import service_account
                _GOOGLE_SERVICE_ACCOUNT_CREDENTIALS = service_account.Credentials
            return _GOOGLE_SERVICE_ACCOUNT_CREDENTIALS.from_service_account_file(
                path,
                scopes=GOOGLE_STT_SCOPES,
            )

        if all(data.get(key) for key in ("client_id", "client_secret", "refresh_token")):
            existing_scopes = data.get("scopes") or data.get("scope") or []
            if isinstance(existing_scopes, str):
                existing_scopes = existing_scopes.split()
            if existing_scopes and GOOGLE_STT_SCOPES[0] not in existing_scopes:
                raise RuntimeError(
                    "Google OAuth 토큰에 Speech-to-Text 권한 범위가 없습니다. "
                    "`gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform`으로 "
                    "Speech 권한이 있는 ADC를 다시 만들거나 서비스 계정 JSON을 사용하세요."
                )
            global _GOOGLE_AUTHORIZED_USER_CREDENTIALS
            if _GOOGLE_AUTHORIZED_USER_CREDENTIALS is None:
                from google.oauth2.credentials import Credentials
                _GOOGLE_AUTHORIZED_USER_CREDENTIALS = Credentials
            return _GOOGLE_AUTHORIZED_USER_CREDENTIALS.from_authorized_user_file(
                path,
                scopes=GOOGLE_STT_SCOPES,
            )

        raise RuntimeError(
            "Google STT credential 파일 형식이 지원되지 않습니다. "
            "service_account JSON 또는 refresh_token 이 있는 authorized-user JSON이 필요합니다."
        )

    def _load_google_stt_credentials(self):
        for path, required in self._google_stt_credential_candidates():
            if not path or not os.path.exists(path):
                if required:
                    raise RuntimeError(f"Google STT credential 파일이 없습니다: {path}")
                continue
            try:
                return self._google_stt_credentials_from_file(path)
            except RuntimeError:
                if required:
                    raise
        return None

    def get_google_speech_client(self):
        with self.model_lock:
            if self.google_speech_client is None:
                self.loading = True
                try:
                    speech = self._load_google_speech_module()
                    try:
                        credentials = self._load_google_stt_credentials()
                        if credentials is None:
                            self.google_speech_client = speech.SpeechClient()
                        else:
                            self.google_speech_client = speech.SpeechClient(credentials=credentials)
                    except RuntimeError:
                        raise
                    except Exception as exc:
                        raise RuntimeError(
                            "Google STT 인증이 필요합니다. "
                            "`gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform`을 실행하거나 "
                            f"Speech 권한이 있는 서비스 계정/authorized-user JSON 경로를 {GOOGLE_STT_CREDENTIAL_ENV}에 설정하세요."
                        ) from exc
                finally:
                    self.loading = False
            return self.google_speech_client

    def _sherpa_model_root(self):
        override = os.environ.get("SHERPA_ONNX_KO_MODEL_PATH", "")
        if override:
            return os.path.expanduser(override)
        return os.path.expanduser(
            "~/.qwen-dictation/models/sherpa-onnx-streaming-zipformer-korean-2024-06-16"
        )

    def _load_sherpa_onnx_module(self):
        try:
            import sherpa_onnx
        except Exception as exc:
            raise RuntimeError(
                "sherpa-onnx Korean 엔진을 쓰려면 sherpa-onnx 패키지가 필요합니다. "
                "`./venv/bin/python -m pip install sherpa-onnx` 후 다시 시도하세요."
            ) from exc
        return sherpa_onnx

    def _first_existing(self, root, names):
        for name in names:
            path = os.path.join(root, name)
            if os.path.exists(path):
                return path
        return ""

    def _locate_sherpa_onnx_model(self):
        root = self._sherpa_model_root()
        tokens = self._first_existing(root, ["tokens.txt"])
        encoder = self._first_existing(
            root,
            [
                "encoder-epoch-99-avg-1.int8.onnx",
                "encoder-epoch-99-avg-1.onnx",
                "encoder.int8.onnx",
                "encoder.onnx",
            ],
        )
        decoder = self._first_existing(
            root,
            [
                "decoder-epoch-99-avg-1.int8.onnx",
                "decoder-epoch-99-avg-1.onnx",
                "decoder.int8.onnx",
                "decoder.onnx",
            ],
        )
        joiner = self._first_existing(
            root,
            [
                "joiner-epoch-99-avg-1.int8.onnx",
                "joiner-epoch-99-avg-1.onnx",
                "joiner.int8.onnx",
                "joiner.onnx",
            ],
        )
        if not all([tokens, encoder, decoder, joiner]):
            raise RuntimeError(
                "sherpa-onnx Korean 모델 파일이 없습니다. "
                f"{root} 아래에 tokens.txt, encoder*.onnx, decoder*.onnx, joiner*.onnx를 두세요."
            )
        return {
            "root": root,
            "tokens": tokens,
            "encoder": encoder,
            "decoder": decoder,
            "joiner": joiner,
        }

    def get_sherpa_onnx_recognizer(self):
        with self.model_lock:
            if self.sherpa_onnx_recognizer is None:
                self.loading = True
                try:
                    sherpa_onnx = self._load_sherpa_onnx_module()
                    model = self._locate_sherpa_onnx_model()
                    self.sherpa_onnx_recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                        tokens=model["tokens"],
                        encoder=model["encoder"],
                        decoder=model["decoder"],
                        joiner=model["joiner"],
                        num_threads=2,
                        sample_rate=16000,
                        feature_dim=80,
                        decoding_method="greedy_search",
                        provider="cpu",
                    )
                finally:
                    self.loading = False
            return self.sherpa_onnx_recognizer

    def _transcribe_google_stt(self, audio_path, language):
        speech = self._load_google_speech_module()
        client = self.get_google_speech_client()
        with open(audio_path, "rb") as f:
            content = f.read()
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code=asr_engines.normalize_google_language(language),
            enable_automatic_punctuation=True,
            model=asr_engines.GOOGLE_STT_MODEL_ID,
        )
        audio = speech.RecognitionAudio(content=content)
        response = client.recognize(config=config, audio=audio)
        parts = []
        for result in getattr(response, "results", []) or []:
            alternatives = getattr(result, "alternatives", []) or []
            if alternatives:
                parts.append(getattr(alternatives[0], "transcript", "") or "")
        return " ".join(part.strip() for part in parts if part.strip()).strip()

    def _transcribe_sherpa_onnx(self, audio_path):
        recognizer = self.get_sherpa_onnx_recognizer()
        samples, sample_rate = sf.read(audio_path, dtype="float32")
        if getattr(samples, "ndim", 1) > 1:
            samples = np.mean(samples, axis=1).astype(np.float32)
        stream = recognizer.create_stream()
        stream.accept_waveform(int(sample_rate), samples)
        if hasattr(stream, "input_finished"):
            stream.input_finished()
        is_ready = getattr(recognizer, "is_ready", None)
        if callable(is_ready):
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
        else:
            recognizer.decode_stream(stream)
        result = recognizer.get_result(stream)
        if isinstance(result, str):
            return result.strip()
        return (getattr(result, "text", "") or "").strip()

    def _result_text(self, result):
        if isinstance(result, str):
            return result.strip()
        return (getattr(result, "text", "") or "").strip()

    def _transcribe_nemotron_stream(self, audio_path, language):
        model = self.get_nemotron_model()
        stream_generate = getattr(model, "stream_generate", None)
        if not callable(stream_generate):
            raise RuntimeError("Nemotron MLX 모델이 stream_generate 네이티브 스트리밍 API를 제공하지 않습니다.")
        samples, sample_rate = sf.read(audio_path, dtype="float32")
        if getattr(samples, "ndim", 1) > 1:
            samples = np.mean(samples, axis=1).astype(np.float32)
        if int(sample_rate) != 16000:
            raise RuntimeError(f"Nemotron MLX stream_generate는 16000 Hz 오디오가 필요합니다: {sample_rate}")
        import mlx.core as mx

        audio = mx.array(np.asarray(samples, dtype=np.float32))
        latest = ""
        for result in stream_generate(
            audio,
            language=asr_engines.normalize_nemotron_language(language),
        ):
            text = self._result_text(result)
            if text:
                latest = text
        return latest

    def preload_current_model(self):
        engine = asr_engines.normalize_asr_engine(self.asr_engine)
        if engine == asr_engines.ASR_ENGINE_NEMOTRON_MLX:
            return self.get_nemotron_model()
        if engine == asr_engines.ASR_ENGINE_GOOGLE_STT:
            return self.get_google_speech_client()
        if engine == asr_engines.ASR_ENGINE_SHERPA_ONNX_KO:
            return self.get_sherpa_onnx_recognizer()
        return self.get_model()

    def transcribe_file(self, audio_path, language=None, context=""):
        # 무음/잡음만 있는 버퍼는 건너뛴다. 라이브 틱은 context="" 로 호출해 누출을 원천
        # 차단하고, 확정 시점에만 등록 용어 context 를 받아 모델에 귀띔한다(누출 가드 동반).
        silence_threshold, _ = volume_peak_thresholds(
            getattr(self, "min_volume", DEFAULT_MIN_VOLUME)
        )
        if audio_peak(audio_path) < silence_threshold:
            return ""
        engine = asr_engines.normalize_asr_engine(self.asr_engine)
        if engine == asr_engines.ASR_ENGINE_NEMOTRON_MLX:
            return self._transcribe_nemotron_stream(audio_path, language)
        if engine == asr_engines.ASR_ENGINE_GOOGLE_STT:
            return self._transcribe_google_stt(audio_path, language)
        if engine == asr_engines.ASR_ENGINE_SHERPA_ONNX_KO:
            return self._transcribe_sherpa_onnx(audio_path)

        model = self.get_model()
        language = normalize_language(language)
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
        # Ctrl/Cmd 같은 modifier 를 홀드 키로 쓰는 동안 합성 backspace 가 섞이지
        # 않도록 Recorder._type 은 modifier flags 를 지운 CGEvent backspace 를 쓴다.
        self.defer_typing_until_stop = False
        self.deferred_text = ""
        self.append_only_until_stop = False
        self._stable_hypo = ""
        self._stable_ticks = 0
        # 스트리밍 루프의 주기 대기를 즉시 깨우는 정지 신호. 키를 떼면 set 되어
        # 다음 확인 주기를 기다리지 않고 곧장 마지막 틱(+Enter)으로 넘어간다.
        self._wake = threading.Event()

    def rebaseline(self):
        """입력창 글자에 대한 소유권을 내려놓는다. 다음 발화는 빈 기준에서 시작해
        백스페이스 없이 커서 위치에 새 글자만 덧붙는다(사용자 수정 보존)."""
        self.rebaseline_pending = True

    def start(self, language=None, live_typing=True, append_only_live=False):
        if self.recording:
            return
        self.finalize_on_stop = True
        self.send_enter_on_stop = False
        self.defer_typing_until_stop = not bool(live_typing)
        self.append_only_until_stop = bool(append_only_live and live_typing)
        self.deferred_text = ""
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

    def _type(self, old, new, append_only=False):
        # Let pynput choose the platform text insertion path. The local Quartz
        # Unicode inserter is unreliable in some focused apps on this macOS
        # build: it can report success internally without inserting text.
        inserter = None
        deleter = plain_backspace if CGEventCreateKeyboardEvent is not None else None
        self.self_type_guard_until = time.time() + 30.0
        try:
            return type_diff(old, new, self.transcriber.pykeyboard,
                             allow_empty=True, insert=inserter, append_only=append_only,
                             delete_backward=deleter)
        finally:
            self.self_type_guard_until = time.time() + SELF_TYPE_GUARD_SETTLE_SEC

    def _transcribe_window(self, window_bytes, language, context=""):
        path = "/tmp/qwen_dictation_stream.wav"
        audio = np.frombuffer(window_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        sf.write(path, audio, 16000)
        return self.transcriber.transcribe_file(path, language=language, context=context)

    def _biased_commit_hypo(self, window, language, unbiased, window_secs):
        """확정 시점에만, 충분히 긴 창에 한해 등록 용어를 모델에 귀띔해 다시 받아쓴다.
        누출 가드(머리표 echo 금지 + 근거 없는 등록어 금지)를 통과할 때만 편향본을 쓰고,
        아니면 무편향본을 그대로 돌려준다. 라이브 틱은 호출하지 않는다(누출 0 유지)."""
        if not asr_engines.asr_engine_supports_context(
            getattr(getattr(self, "transcriber", None), "asr_engine", asr_engines.DEFAULT_ASR_ENGINE)
        ):
            return unbiased
        vocab = getattr(self, "session_vocab", None) or []
        if not vocab or window_secs < BIAS_MIN_WINDOW_SEC:
            return unbiased
        domain = getattr(self.app, "domain_context", "")
        context = vocabulary.build_context(vocab, domain)
        if not context:
            return unbiased
        biased = self._transcribe_window(window, language, context=context)
        if looks_like_context_label_echo(biased):
            return unbiased  # context 머리표 자체가 새어나옴 → 거부
        biased = term_correct.correct_terms(biased, vocab)
        if not term_correct.context_bias_is_safe(unbiased, biased, vocab):
            return unbiased  # 근거 없는 등록어가 튀어나옴(누출) → 거부
        return biased

    def _stream_tick(self, language, allow_stopped=False):
        # 사용자가 직접 고친 직후라면 기준점을 현재로 리셋한다. 리스너 스레드와의
        # 경합을 피하려 플래그만 받아 스트리밍 스레드인 여기서 실제 상태를 바꾼다.
        if self.rebaseline_pending:
            with self.audio_lock:
                self.window_start = len(self.audio_frames)
            self.committed_text = ""
            self.last_typed = ""
            self._stable_hypo = ""
            self._stable_ticks = 0
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
        engine = asr_engines.normalize_asr_engine(
            getattr(self.app, "asr_engine", asr_engines.DEFAULT_ASR_ENGINE)
        )
        qwen_original_live = (
            engine == getattr(asr_engines, "ASR_ENGINE_QWEN_ORIGINAL", "qwen_original")
        )
        set_engine = getattr(self.transcriber, "set_engine", None)
        if set_engine is not None:
            set_engine(engine)
        else:
            self.transcriber.asr_engine = engine
        if pcm_peak(window) < start_threshold:
            with self.audio_lock:
                self.window_start = max(0, frame_count - SPEECH_START_LOOKBACK_CHUNKS)
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
        window_secs = len(window) / 2.0 / 16000.0
        finalizing = bool(allow_stopped and not self.recording)
        # 한국어(한글)도 영어도 아닌 언어로 새면(짧은 라이브 창에서 auto 감지가 흔들려
        # 중국어·일본어·러시아어 등으로 빠짐): 확정 직전이면 한국어로 다시 받아써서
        # 외국어 확정을 막고, 아직 말하는 중이면 화면에 안 띄우고 직전 글자를 유지한다
        # (빈 토막처럼 처리 → '깜빡임' 없이 직전 한국어 유지).
        if hypo and looks_like_foreign_language(hypo):
            if finalizing or should_commit(window_secs, paused, MAX_WINDOW_SEC):
                forced = self._transcribe_window(window, "Korean")
                hypo = forced if not looks_like_foreign_language(forced) else ""
            else:
                hypo = ""
        # 등록 용어로 사후 교정한다(라이브 틱은 모델에 용어를 안 줬으므로 여기서만 반영).
        unbiased = term_correct.correct_terms(hypo, getattr(self, "session_vocab", None) or [])
        if unbiased:
            if unbiased == getattr(self, "_stable_hypo", ""):
                self._stable_ticks = getattr(self, "_stable_ticks", 0) + 1
            else:
                self._stable_hypo = unbiased
                self._stable_ticks = 1
        else:
            self._stable_hypo = ""
            self._stable_ticks = 0
        stable_commit = bool(
            unbiased
            and self.recording
            and not allow_stopped
            and getattr(self, "_stable_ticks", 0) >= STABLE_COMMIT_TICKS
        )
        committing = bool(
            unbiased and (
                finalizing
                or stable_commit
                or should_commit(window_secs, paused, MAX_WINDOW_SEC)
            )
        )
        if committing:
            # 확정 시점엔 등록 용어를 모델에 귀띔해 다시 받아쓴다(증거가 강해 누출이 적다).
            # 누출 가드를 통과하면 편향본을, 아니면 무편향본을 확정한다. 마지막 말까지 전부.
            hypo = self._biased_commit_hypo(window, language, unbiased, window_secs)
            if looks_like_foreign_language(hypo):
                hypo = unbiased  # 편향 재받아쓰기가 외국어로 새면 무편향(한국어) 유지
            shown = hypo
        else:
            hypo = unbiased
            if qwen_original_live:
                # Qwen Original: rolling WAV 재인식 결과를 바로 표시한다. 이 모드는
                # 원래처럼 중간 hypothesis를 backspace rewrite 하며 따라간다.
                shown = hypo
            else:
                # LocalAgreement-2: '연속 두 번 같은' 앞부분만 화면에 표시한다. 확정
                # 앞부분은 단조 증가만 하므로 이미 친 글자를 지우거나 바꾸지 않는다.
                prev = getattr(self, "_la_prev_hypo", "")
                confirmed = getattr(self, "_la_confirmed", "")
                agreed = agreed_word_prefix(prev, hypo)
                cw, aw = confirmed.split(), agreed.split()
                if len(aw) > len(cw) and aw[: len(cw)] == cw:
                    confirmed = agreed  # 합의된 앞부분이 더 늘면 확정 연장
                shown = confirmed
                self._la_confirmed = confirmed
        self._la_prev_hypo = hypo
        # 단위가 붙은 한국어 수사만 아라비아 숫자로 바꾼다('삼 밀리'->3밀리). 변환은
        # idempotent 라 확정 텍스트에 다시 적용해도 안전하다.
        target = text_normalize.normalize_numbers(self.committed_text + shown)
        defer_typing = (
            getattr(self, "defer_typing_until_stop", False)
            and self.recording
            and not allow_stopped
        )
        append_only = False
        if not defer_typing:
            append_only = (
                self.recording
                and not allow_stopped
                and not qwen_original_live
            )
            # 타이핑 중과 직후 짧은 보호 시간에는 우리가 만든 합성 키 이벤트가 들어오므로, 그 사이
            # 리스너가 키를 사용자 수동 편집으로 오인하지 않도록 가드 시각을 세운다.
            self.self_type_guard_until = time.time() + 30.0
            try:
                self.last_typed = self._type(self.last_typed, target, append_only=append_only)
            finally:
                self.self_type_guard_until = time.time() + SELF_TYPE_GUARD_SETTLE_SEC
            self.deferred_text = ""
        elif target:
            self.deferred_text = target
        if committing:
            self.committed_text = self.last_typed if append_only else target
            self._la_prev_hypo = ""
            self._la_confirmed = ""
            self._stable_hypo = ""
            self._stable_ticks = 0
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
        self.deferred_text = ""
        self._la_prev_hypo = ""
        self._la_confirmed = ""
        self._stable_hypo = ""
        self._stable_ticks = 0
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
        deferred = getattr(self, "deferred_text", "")
        if deferred and self.last_typed != deferred:
            self.self_type_guard_until = time.time() + 30.0
            try:
                self.last_typed = self._type(self.last_typed, deferred)
            finally:
                self.self_type_guard_until = time.time() + SELF_TYPE_GUARD_SETTLE_SEC
            self.deferred_text = ""
        # Enter 를 먼저 보내고(사용자가 체감하는 지연), 기록 저장은 그 뒤로 미룬다.
        # 마지막 틱에서 새로 친 글자가 있으면 짧은 반영 대기를, 없으면 곧장 보낸다.
        if getattr(self, "send_enter_on_stop", False) and self.last_typed.strip():
            self._send_enter(settle=0.03 if self.last_typed != typed_before else 0.0)
        dictation_history.add_history(self.last_typed)


class MultiHotkeyListener:
    """사용자 지정 단일키 또는 조합키 2개로 실시간 받아쓰기를 구동한다.

    - 오른쪽 Ctrl(ctrl_r): 홀드 — 누르는 동안 녹음, 떼면 정지.
    - 토글키: 눌러 시작, 다시 눌러 정지. fn도 설정 가능.
    둘 다 streaming: 말하는 대로 입력창에 실시간 타이핑(문맥 보정 포함).
    동시에 하나의 트리거만 활성(active_trigger).
    """

    def __init__(self, app, hold_key="ctrl_r", toggle_key="alt_r"):
        self.app = app
        self.hold_key = hotkeys.normalize_hotkey(hold_key)
        self.toggle_key = hotkeys.normalize_hotkey(toggle_key)
        self.hold_parts = hotkeys.hotkey_parts(self.hold_key)
        self.toggle_parts = hotkeys.hotkey_parts(self.toggle_key)
        self.pressed = set()
        self.toggle_latched = False
        self.active_trigger = None  # None | "hold" | "toggle"

    def _release_tokens(self, token):
        if token in hotkeys.MODIFIERS:
            base = token.removesuffix("_r")
            return {base, f"{base}_r"}
        return {token}

    def _press_tokens(self, token):
        return {token}

    def _begin(self, trigger):
        if self.app.started:
            return
        self.active_trigger = trigger
        try:
            self.app._live_typing_for_next_start = True
            self.app._append_only_for_next_start = False
        except Exception:
            pass
        recorder = getattr(self.app, "recorder", None)
        if recorder is not None:
            recorder.defer_typing_until_stop = False
            recorder.append_only_until_stop = False
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
        self.pressed.update(self._press_tokens(token))
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
        for release_token in self._release_tokens(token):
            self.pressed.discard(release_token)
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
        ]
        for engine in asr_engines.available_asr_engines():
            item = rumps.MenuItem(self._asr_engine_menu_title(engine), callback=self.change_asr_engine)
            item.engine_id = engine["id"]
            menu.append(item)
        menu.extend([
            None,
            rumps.MenuItem("Open Settings Dashboard", callback=self.open_dashboard),
            None,
        ])
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

    def _model_loading(self):
        """모델을 실제로 올리는 중인가(HUD '불러오는 중' 표시 조건). 로드 실패 시엔
        transcriber.loading 이 finally 에서 내려가므로 표시가 영원히 남지 않는다."""
        rec = getattr(self, "recorder", None)
        tr = getattr(rec, "transcriber", None) if rec else None
        return bool(tr and getattr(tr, "loading", False))

    @staticmethod
    def _loading_pulse():
        """로딩 막대를 숨쉬듯 움직일 0~1 삼각파. math import 없이 시간만으로 만든다."""
        frac = (time.time() % 0.9) / 0.9      # 0.9초 주기 0→1 톱니
        return 1.0 - abs(2.0 * frac - 1.0)    # 0→1→0 삼각파

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

            if self._model_loading():
                # 모델 cold load(~7초) 중엔 시작 워밍업이든 첫 받아쓰기든, 막대를 숨쉬듯
                # 펄스시키고 '불러오는 중'을 띄워 멈춘 게 아니라 준비 중임을 알린다.
                if self.started and self.start_time is not None:
                    elapsed = int(time.time() - self.start_time)
                    self.elapsed_time = elapsed
                    minutes, seconds = divmod(elapsed, 60)
                    self.title = f"({minutes:02d}:{seconds:02d}) 🔴"
                ov.update(self._loading_pulse(), 0)
                ov.set_processing(False)
                ov.show_status("모델 불러오는 중…")
            elif self.started and self.start_time is not None:
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
            "hold_key": getattr(self, "hold_key", "ctrl_r"),
            "toggle_key": getattr(self, "toggle_key", "alt_r"),
            "min_volume": getattr(self, "min_volume", DEFAULT_MIN_VOLUME),
            "asr_engine": asr_engines.normalize_asr_engine(
                getattr(self, "asr_engine", asr_engines.DEFAULT_ASR_ENGINE)
            ),
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
        self.asr_engine = asr_engines.normalize_asr_engine(
            cfg.get("asr_engine", asr_engines.DEFAULT_ASR_ENGINE)
        )
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
            self.recorder.transcriber.set_engine(self.asr_engine)
        self.sync_menu_state()

    @staticmethod
    def _asr_engine_menu_title(engine):
        return f"Model: {engine.get('short_label') or engine['label']}"

    def sync_menu_state(self):
        for lang in self.languages:
            title = f"Language: {lang}"
            if title in self.menu:
                self.menu[title].state = int(self.current_language == lang)
        selected_engine = asr_engines.normalize_asr_engine(
            getattr(self, "asr_engine", asr_engines.DEFAULT_ASR_ENGINE)
        )
        for engine in asr_engines.available_asr_engines():
            title = self._asr_engine_menu_title(engine)
            if title in self.menu:
                self.menu[title].state = int(selected_engine == engine["id"])

    def open_dashboard(self, _):
        settings_window.open_settings("http://127.0.0.1:5001")

    def change_language(self, sender):
        self.current_language = sender.title.replace("Language: ", "")
        self.sync_menu_state()
        self.save_settings()

    def set_asr_engine(self, engine):
        self.asr_engine = asr_engines.normalize_asr_engine(engine)
        if getattr(self, "recorder", None) is not None:
            self.recorder.transcriber.set_engine(self.asr_engine)
        self.sync_menu_state()

    def change_asr_engine(self, sender):
        self.set_asr_engine(getattr(sender, "engine_id", asr_engines.DEFAULT_ASR_ENGINE))
        self.save_settings()

    @rumps.clicked("Start Recording")
    def start_app(self, _):
        if self.started or self.processing_active:
            return
        print("Listening...")
        self.started = True
        self.menu["Start Recording"].set_callback(None)
        self.menu["Stop Recording"].set_callback(self.stop_app)
        live_typing = bool(getattr(self, "_live_typing_for_next_start", True))
        self._live_typing_for_next_start = True
        append_only_live = bool(getattr(self, "_append_only_for_next_start", False))
        self._append_only_for_next_start = False
        self.recorder.start(
            self.current_language,
            live_typing=live_typing,
            append_only_live=append_only_live,
        )
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
            hold_key=getattr(self, "hold_key", "ctrl_r"),
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

        self._global_listener = SafeKeyboardListener(
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
    app = StatusBarApp(languages=languages, max_time=args.max_time)
    print(f"Initializing {asr_engines.asr_engine_label(app.asr_engine)} on {device}...")

    transcriber = SpeechTranscriber(device, dtype, asr_engine=app.asr_engine)
    recorder = Recorder(transcriber, app)
    app.recorder = recorder

    # 선택된 모델을 백그라운드에서 미리 올려둔다(앱 켤 때 cold load 를 첫 받아쓰기
    # 시점이 아니라 시작 시점에 숨긴다 → 첫 받아쓰기도 바로 빠르게).
    def _warmup_model():
        try:
            transcriber.preload_current_model()
            print(f"Model preloaded ({transcriber.current_engine_label()}).")
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
