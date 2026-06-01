# Qwen 실시간 스트리밍 받아쓰기 (토글·홀드, 입력창 직접 타이핑) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 단축키 두 개(오른쪽 Cmd=홀드, 오른쪽 Option=토글) 모두, 말하는 동안 Qwen이 ~0.8초마다 받아써서 **지금 포커스된 입력창에 글자를 실시간으로 직접 타이핑**하고, 문맥이 바뀌면 앞부분을 고쳐 쓰며, 쉬는 지점(잠깐 멈춤/문장 끝)마다 앞부분을 "확정"하고 버퍼를 비워 길게 말해도 느려지지 않게 한다. 리뷰 패널·배치·자동전송은 제거한다.

**Architecture:** 녹음은 기존 pyaudio 스레드(`_record_impl`)가 `audio_frames`에 계속 쌓는다. 새 스레드 `_stream_loop`가 주기적으로 **"확정 지점 이후의 오디오 창(window)"만** Qwen으로 받아써서, `committed_text + hypothesis`를 목표 텍스트로 삼아 `type_diff`로 화면에 친 것과의 차이만 타이핑한다. 끝쪽 오디오가 조용해지거나(=쉼) 창이 너무 길어지면 현재 가설을 확정(`committed_text`에 누적)하고 창 시작점을 현재로 옮겨 버퍼를 비운다. 두 단축키 모두 이 스트리밍 한 경로만 쓴다.

**Tech Stack:** Python 3.11, pyaudio(16k mono 캡처), qwen_asr(`transcribe_file`, 무음게이트+등록단어 context+echo가드 이미 포함), pynput(`type_diff`로 실시간 타이핑), rumps. 테스트 pytest. `whisper-dictation.py`는 하이픈이라 importlib 로드.

**현재 테스트 수:** 68 passed (시작점).

---

## 배경: 현재 흐름과 무엇을 바꾸나 (실측)

- 현재 `Recorder._record_impl`(whisper-dictation.py:300-345)는 pyaudio로 `audio_frames`에 쌓고, **끝나면 `_run_batch_transcription`을 한 번 호출**한다. 즉 "녹음 다 하고 끝에 한 번 변환"뿐, 실시간 스트리밍 루프가 없다.
- `_run_batch_transcription`(357-388)은 모드에 따라 자동전송/리뷰패널/한번붙여넣기로 갈린다. **이 전체를 스트리밍으로 대체**하고 리뷰·배치 분기를 제거한다.
- `MultiHotkeyListener`(450-490): 현재 `hold=alt_r→STREAMING`, `toggle=cmd_r→BATCH_PASTE`. → **`hold=cmd_r`, `toggle=alt_r`, 둘 다 `STREAMING`**으로 바꾼다.
- 재사용: `type_diff(old, new, kb)`(190)는 공통 접두사까지 백스페이스 후 나머지를 친다 = 실시간 타이핑/문맥보정에 그대로 씀. `transcribe_file`(243)은 무음게이트(`SILENCE_PEAK_THRESHOLD`)+등록단어 context+echo가드를 이미 포함.
- `audio_level`/오버레이 막대(녹음 중 화면 아래 알약)는 그대로 유지된다.

**핵심 설계값:**
- 갱신 간격 `STREAM_INTERVAL = 0.8`초.
- 확정용 끝쪽 무음 길이 `PAUSE_SILENCE_SEC = 0.8`초(이만큼 끝이 조용하면 쉼으로 보고 확정).
- 창 최대 길이 `MAX_WINDOW_SEC = 12.0`초(쉼 없이 계속 말해도 이 길이 넘으면 강제 확정 → 느려짐 방지).
- 오디오: int16 mono 16kHz → 1초 = 32000 bytes(= 16000 samples × 2).

---

## File Structure

- **Modify** `whisper-dictation.py`:
  - 신규 순수 함수 `trailing_silence(audio_bytes, rate, peak_threshold, secs)` (끝쪽이 조용한지) + `should_commit(window_secs, paused, max_secs)` (확정할지).
  - `Recorder`: `_stream_loop`(실시간 루프) + `_transcribe_window`(bytes→텍스트), `start`에서 스트리밍 스레드 시작, `_record_impl`에서 배치 호출 제거, `stop` 그대로(플래그만).
  - `_run_batch_transcription` 및 그 안의 리뷰/배치 분기 제거.
  - `MultiHotkeyListener`: 기본 키 스왑(hold=cmd_r, toggle=alt_r), 둘 다 `MODE_STREAMING`.
  - 상수 `STREAM_INTERVAL`, `PAUSE_SILENCE_SEC`, `MAX_WINDOW_SEC` 추가.
- **Modify** `app_config.py`: `hold_key` 기본 `cmd_r`, `toggle_key` 기본 `alt_r`.
- **Test** `test_streaming.py` (순수 함수: trailing_silence, should_commit), `test_hotkey_config.py`(기본 키 스왑 반영).

---

## Task 1: 끝쪽 무음 판정 + 확정 판정 순수 함수

실시간 루프가 "지금 쉬었나? 확정할까?"를 정하는 순수 로직. pyaudio/qwen 없이 완전 테스트.

**Files:**
- Modify: `whisper-dictation.py` (모듈 최상위, `audio_peak` 정의 근처)
- Test: `test_streaming.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# test_streaming.py
import importlib.util
import numpy as np


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pcm(samples_int16):
    return np.asarray(samples_int16, dtype=np.int16).tobytes()


def test_trailing_silence_true_when_tail_quiet():
    wd = _load()
    # 1초 큰 소리 + 1초 무음, 끝 0.8초가 조용 → True
    loud = list((np.random.RandomState(0).randn(16000) * 6000).astype(np.int16))
    quiet = [0] * 16000
    audio = _pcm(loud + quiet)
    assert wd.trailing_silence(audio, 16000, 1000.0, 0.8) is True


def test_trailing_silence_false_when_tail_loud():
    wd = _load()
    loud = list((np.random.RandomState(1).randn(16000) * 6000).astype(np.int16))
    audio = _pcm(loud + loud)  # 끝까지 시끄러움
    assert wd.trailing_silence(audio, 16000, 1000.0, 0.8) is False


def test_trailing_silence_short_audio_false():
    wd = _load()
    # 0.8초보다 짧으면 아직 쉼 판정 안 함(False)
    audio = _pcm([0] * 1000)
    assert wd.trailing_silence(audio, 16000, 1000.0, 0.8) is False


def test_should_commit_on_pause():
    wd = _load()
    assert wd.should_commit(window_secs=3.0, paused=True, max_secs=12.0) is True


def test_should_commit_on_max_window():
    wd = _load()
    assert wd.should_commit(window_secs=12.5, paused=False, max_secs=12.0) is True


def test_should_not_commit_midspeech():
    wd = _load()
    assert wd.should_commit(window_secs=3.0, paused=False, max_secs=12.0) is False
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/python -m pytest test_streaming.py -v`
Expected: FAIL — `AttributeError: module 'wd' has no attribute 'trailing_silence'`

- [ ] **Step 3: 구현 — 두 순수 함수 추가**

`whisper-dictation.py`의 `audio_peak` 함수 정의 바로 아래에 추가:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `./venv/bin/python -m pytest test_streaming.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py test_streaming.py
git commit -m "feat: trailing_silence + should_commit pure helpers for streaming commit logic"
```

---

## Task 2: 단축키 스왑 + 둘 다 스트리밍

홀드=오른쪽 Cmd, 토글=오른쪽 Option. 두 트리거 모두 `MODE_STREAMING`으로 시작.

**Files:**
- Modify: `app_config.py` (기본 키)
- Modify: `whisper-dictation.py` (`MultiHotkeyListener`)
- Test: `test_hotkey_config.py`

- [ ] **Step 1: 실패하는 테스트 추가** (`test_hotkey_config.py` 끝)

```python
def test_default_keys_are_cmd_hold_option_toggle():
    import app_config
    cfg = dict(app_config.DEFAULTS)
    assert cfg["hold_key"] == "cmd_r"      # 홀드 = 오른쪽 Cmd
    assert cfg["toggle_key"] == "alt_r"    # 토글 = 오른쪽 Option


def test_multi_listener_both_triggers_use_streaming():
    wd = _load()
    starts = []

    class App:
        started = False
        def begin_session(self, mode): starts.append(mode); self.started = True
        def stop_app(self, _): self.started = False
    app = App()
    lis = wd.MultiHotkeyListener(app, hold_key=wd.keyboard.Key.cmd_r, toggle_key=wd.keyboard.Key.alt_r)
    # 홀드(누름) → streaming 시작
    lis.on_key_press(wd.keyboard.Key.cmd_r)
    # 토글(누름) → 이미 시작 중이면 무시되므로, 새 인스턴스로 토글 확인
    app2 = App()
    lis2 = wd.MultiHotkeyListener(app2, hold_key=wd.keyboard.Key.cmd_r, toggle_key=wd.keyboard.Key.alt_r)
    lis2.on_key_press(wd.keyboard.Key.alt_r)
    assert starts == [wd.MODE_STREAMING]            # 홀드가 streaming
    assert app2.started and starts.count(wd.MODE_STREAMING) >= 1  # 토글도 streaming
```

(주의: `wd.keyboard`는 모듈에서 `from pynput import keyboard`로 들어와 있어 `wd.keyboard`로 접근 가능. `dispatch_app`이 `begin_session`을 직접 호출하도록 App에 `dispatch_to_main`이 없으면 그냥 콜백 실행됨.)

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/python -m pytest test_hotkey_config.py -v`
Expected: FAIL — 기본 키가 아직 `alt_r`/`cmd_r`(반대), 토글이 `MODE_BATCH_PASTE`.

- [ ] **Step 3: 구현**

(a) `app_config.py` DEFAULTS:
```python
    "hotkey_mode": "multi",
    "hold_key": "cmd_r",
    "toggle_key": "alt_r",
```

(b) `whisper-dictation.py` `MultiHotkeyListener.__init__` 기본값:
```python
    def __init__(self, app, hold_key=keyboard.Key.cmd_r, toggle_key=keyboard.Key.alt_r):
```

(c) 같은 클래스 `on_key_press`의 토글 분기에서 `MODE_BATCH_PASTE` → `MODE_STREAMING`:
```python
    def on_key_press(self, key):
        if key == self.hold_key:
            if not self.app.started:
                self._begin("hold", MODE_STREAMING)
        elif key == self.toggle_key:
            if self.active_trigger == "toggle":
                self._end("toggle")
            elif not self.app.started:
                self._begin("toggle", MODE_STREAMING)
```

(d) 클래스 docstring(451-458)의 설명 두 줄을 현실에 맞게 교체:
```python
    """오른쪽 단일 수정키 2개로 실시간 스트리밍 받아쓰기를 구동한다.

    - 오른쪽 Cmd(cmd_r): 홀드 — 누르는 동안 녹음, 떼면 정지.
    - 오른쪽 Option(alt_r): 토글 — 눌러 시작, 다시 눌러 정지.
    둘 다 streaming: 말하는 대로 입력창에 실시간 타이핑(문맥 보정 포함).
    동시에 하나의 트리거만 활성(active_trigger).
    """
```

- [ ] **Step 4: 통과 + 회귀**

Run: `./venv/bin/python -m py_compile whisper-dictation.py app_config.py` 후 `./venv/bin/python -m pytest -q`
Expected: 컴파일 성공. 기존 `test_hotkey_config`의 옛 기본값(alt_r/cmd_r) 검증이 있으면 그 단언을 새 값으로 함께 고친다(아래 grep로 확인 후 수정).
점검: `grep -n "alt_r\|cmd_r\|MultiHotkeyListener(" test_hotkey_config.py` → 기본 키를 단언하는 줄이 있으면 cmd_r(hold)/alt_r(toggle)로 갱신.

- [ ] **Step 5: 커밋**

```bash
git add app_config.py whisper-dictation.py test_hotkey_config.py
git commit -m "feat: swap hotkeys (Cmd=hold, Option=toggle); both trigger streaming"
```

---

## Task 3: 실시간 스트리밍 루프 (창 단위 받아쓰기 + 확정/트림)

녹음 중 주기적으로 "확정 지점 이후 창"만 받아써서 입력창에 실시간 타이핑하고, 쉬는 지점에서 확정·버퍼 비움.

**Files:**
- Modify: `whisper-dictation.py` (`Recorder`)
- Test: `test_streaming.py` (창/확정 상태 전이를 FakeTranscriber로)

- [ ] **Step 1: 실패하는 테스트 추가** (`test_streaming.py` 끝)

스트리밍 한 "틱"의 핵심 로직을 순수 메서드 `_stream_tick`으로 분리해 테스트한다. 입력: 현재 창 bytes·언어. 동작: 받아써서 `committed_text + hypothesis`를 만들고 `type_diff`로 타이핑, 확정 조건이면 `committed_text` 누적 + 창 시작 인덱스 전진. 타이핑은 주입한 fake로 기록.

```python
def _make_recorder(wd, monkeypatch, hypo_by_call):
    # rumps 앱 없이 Recorder 의 스트리밍 부분만 테스트
    class FakeTranscriber:
        def __init__(self): self.calls = 0
        # _transcribe_window 가 호출하는 transcribe_file 흉내는 아래서 monkeypatch
    rec = wd.Recorder.__new__(wd.Recorder)
    rec.audio_lock = __import__("threading").Lock()
    rec.audio_frames = []
    rec.window_start = 0
    rec.committed_text = ""
    rec.last_typed = ""
    rec.typed_log = []
    # type 함수 주입: (old,new)->new, 로그 기록
    rec._type = lambda old, new: (rec.typed_log.append(new) or new)
    # _transcribe_window 를 가설 시퀀스로 대체
    seq = list(hypo_by_call)
    rec._transcribe_window = lambda window_bytes, language: seq.pop(0) if seq else ""
    return rec


def test_stream_tick_types_committed_plus_hypothesis(monkeypatch):
    wd = _load()
    rec = _make_recorder(wd, monkeypatch, ["안녕"])
    # 시끄러운 1초(확정 안 됨: 끝이 시끄러움)
    import numpy as np
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "안녕"
    assert rec.committed_text == ""          # 안 쉬었으니 확정 안 됨
    assert rec.window_start == 0


def test_stream_tick_commits_on_pause_and_advances_window():
    wd = _load()
    import numpy as np
    rec = _make_recorder(wd, None, ["안녕하세요"])
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    quiet = (np.zeros(16000, dtype=np.int16)).tobytes()  # 끝 1초 무음 → 쉼
    with rec.audio_lock:
        rec.audio_frames = [loud, quiet]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "안녕하세요"
    assert rec.committed_text == "안녕하세요"   # 쉬었으니 확정
    assert rec.window_start == 2               # 창 시작이 현재 프레임 끝으로 전진
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/python -m pytest test_streaming.py -v`
Expected: FAIL — `_stream_tick` / `_transcribe_window` 없음.

- [ ] **Step 3: 구현 — 상수 + Recorder 메서드**

(a) 모듈 상수(파일 상단 `SILENCE_PEAK_THRESHOLD = 1000.0` 아래)에 추가:
```python
STREAM_INTERVAL = 0.8        # 초: 스트리밍 갱신 주기
PAUSE_SILENCE_SEC = 0.8      # 초: 끝이 이만큼 조용하면 쉼 → 확정
MAX_WINDOW_SEC = 12.0        # 초: 창이 이보다 길면 강제 확정(느려짐 방지)
```

(b) `Recorder.__init__`에 스트리밍 상태 추가(다른 init 옆):
```python
        self.stream_thread = None
        self.window_start = 0
        self.committed_text = ""
        self.last_typed = ""
```

(c) `Recorder`에 메서드 추가(`_write_current_audio` 근처):
```python
    def _type(self, old, new):
        return type_diff(old, new, self.transcriber.pykeyboard)

    def _transcribe_window(self, window_bytes, language):
        path = "/tmp/qwen_dictation_stream.wav"
        audio = np.frombuffer(window_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        sf.write(path, audio, 16000)
        return self.transcriber.transcribe_file(
            path, language=language, model_size=self.app.selected_model
        )

    def _stream_tick(self, language):
        with self.audio_lock:
            window = b"".join(self.audio_frames[self.window_start:])
            frame_count = len(self.audio_frames)
        if not window:
            return
        hypo = self._transcribe_window(window, language)
        target = self.committed_text + hypo
        self.last_typed = self._type(self.last_typed, target)
        window_secs = len(window) / 2.0 / 16000.0
        paused = trailing_silence(window, 16000, SILENCE_PEAK_THRESHOLD, PAUSE_SILENCE_SEC)
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
        # 정지 후 마지막 한 번 더(남은 창 반영)
        try:
            self._stream_tick(language)
        except Exception as exc:
            print(f"Streaming final tick error: {exc}")
```

- [ ] **Step 4: 통과 확인**

Run: `./venv/bin/python -m pytest test_streaming.py -v`
Expected: PASS (8 passed: Task1의 6 + 2).

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py test_streaming.py
git commit -m "feat: streaming tick/loop — window transcribe + live type_diff + pause-commit/trim"
```

---

## Task 4: 배선 — 녹음 시작 시 스트리밍 스레드, 배치/리뷰 제거

녹음 시작과 동시에 캡처 스레드 + 스트리밍 스레드를 돌리고, 끝의 배치 변환·리뷰·자동전송을 없앤다.

**Files:**
- Modify: `whisper-dictation.py` (`Recorder.start`, `_record_impl`, `_run_batch_transcription` 제거)
- Test: 없음(통합 — 단위 로직은 Task1·3에서 끝). 컴파일+grep 점검.

- [ ] **Step 1: `start`에서 스트리밍 스레드 시작**

`Recorder.start`(276-284)를 다음으로 교체:
```python
    def start(self, language=None):
        if self.recording:
            return
        self.audio_frames = []
        self.recording = True
        self.session_mode = self.app.mode
        self._start_hud()
        self.record_thread = threading.Thread(target=self._record_impl, args=(language,), daemon=True)
        self.record_thread.start()
        self.stream_thread = threading.Thread(target=self._stream_loop, args=(language,), daemon=True)
        self.stream_thread.start()
```

- [ ] **Step 2: `_record_impl`은 캡처만 — 끝의 배치 호출 제거**

`_record_impl`(300-345) 마지막 줄
```python
        self._run_batch_transcription(language, self.session_mode)
```
을 **삭제**한다(캡처만 하고, 타이핑은 `_stream_loop`가 담당). 그 위 `finally` 블록까지는 그대로 둔다.

- [ ] **Step 3: 배치/리뷰 함수 제거**

`_run_batch_transcription`(357-388) 메서드 전체를 삭제한다(스트리밍이 출력을 담당하므로 불필요). 리뷰 패널 호출(`request_review`)도 이로써 트리거되지 않는다.

- [ ] **Step 4: 컴파일 + grep 점검 + 전체 회귀**

Run:
```bash
./venv/bin/python -m py_compile whisper-dictation.py
grep -n "_run_batch_transcription\|request_review\|MODE_BATCH_PASTE\|MODE_BATCH_SUBMIT" whisper-dictation.py
./venv/bin/python -m pytest -q
```
Expected: 컴파일 성공. `_run_batch_transcription` 정의/호출이 없어야 함(상수 `MODE_BATCH_*`는 정의만 남아도 무방). 전체 테스트 통과(68 + Task1·3의 8 - 변경분 ≈ 76 근처, 실패 0).

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py
git commit -m "feat: wire both hotkeys to live streaming; remove batch/review path"
```

---

## Task 5: .app 재빌드 + 실사용 검증 안내 + 문서

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: 재빌드 + 재서명**

Run: `bash build_app.sh 2>&1 | tail -8`
Expected: `dist/Qwen Dictation.app` 재생성 + (build_app.sh의 codesign 단계로) 서명 유효. 치명적 에러 없음.

- [ ] **Step 2: 기동 점검**
```bash
pkill -f "Qwen Dictation.app/Contents/MacOS" 2>/dev/null; sleep 1
( "dist/Qwen Dictation.app/Contents/MacOS/Qwen Dictation" > /tmp/qwen_stream_run.log 2>&1 & P=$!; sleep 20; kill $P 2>/dev/null )
grep -iE "error|traceback|Running|Dashboard" /tmp/qwen_stream_run.log | head
pkill -f "Qwen Dictation.app/Contents/MacOS" 2>/dev/null || true
```
Expected: traceback 없음, "Running Qwen Dictation" 보임.

- [ ] **Step 3: README 갱신** — 모드 설명을 "실시간 스트리밍 2개(Cmd 홀드 / Option 토글), 입력창에 바로 타이핑, 문맥 보정, 리뷰/배치 없음"으로 교체.

- [ ] **Step 4: CLAUDE.md 갱신** — 단축키·동작 설명을 "두 단축키 모두 Qwen 실시간 스트리밍(창 단위 받아쓰기 + type_diff 실시간 타이핑 + 쉬는 지점 확정/트림). 리뷰/배치 제거. Cmd=홀드, Option=토글" 으로 갱신.

- [ ] **Step 5: 커밋**
```bash
git add README.md CLAUDE.md
git commit -m "docs: live streaming dictation (Cmd hold / Option toggle), batch/review removed"
```

- [ ] **Step 6: 사용자 실사용 안내(자동화 불가)**
> **반드시 좋은 마이크(예: MATA STUDIO)를 시스템 기본 입력으로** 두고: 새 앱 우클릭→열기 → 음성인식/마이크 권한 허용 → 입력창에 커서 두고 → 오른쪽 Cmd 누른 채 말하기(또는 오른쪽 Option 눌러 토글) → 글자가 ~1초 간격으로 줄줄 들어오고, 이어 말하면 앞부분이 문맥에 맞게 고쳐지며, 잠깐 쉬면 그 앞이 확정되는지 확인.

---

## Self-Review (작성자 점검)

**1. 스펙 커버리지:** "실시간 타이핑"=`_stream_loop`+`type_diff` ✓ / "문맥 보정"=매 틱 `committed_text+hypothesis` 재타이핑(type_diff 백스페이스) ✓ / "쉬는 지점 확정·길어도 안 느려짐"=`trailing_silence`+`MAX_WINDOW_SEC`로 창 트림 ✓ / "입력창 직접"=type_diff 합성 타이핑 ✓ / "Cmd 홀드·Option 토글, 둘 다 streaming"=Task2 ✓ / "리뷰·배치 제거"=Task4 ✓ / 엔진 Qwen 유지(transcribe_file: 무음게이트+등록단어+echo가드 그대로) ✓.

**2. 플레이스홀더 스캔:** 모든 코드 스텝 실제 코드. 통합부(실제 마이크·타이핑·Qwen)는 헤드리스 불가로 사용자 실행 명시. ✓

**3. 타입/이름 일치:** `trailing_silence`/`should_commit`(Task1)→`_stream_tick`(Task3) 사용. `_transcribe_window`/`_type`/`_stream_tick`/`_stream_loop`/`window_start`/`committed_text`/`last_typed`(Task3)→`start`(Task4) 사용. `hold_key=cmd_r`/`toggle_key=alt_r`(Task2)는 `app_config.DEFAULTS`↔`MultiHotkeyListener` 일치. `type_diff`(기존)·`SILENCE_PEAK_THRESHOLD`(기존) 재사용. ✓

**알려진 한계(실행자 인지):** ①애플처럼 글자단위로 매끄럽진 않다 — 단어가 ~1초 간격으로 뜨고 보정 시 깜빡인다(모델이 청크 단위라 불가피). ②확정 후 아주 오래된(>창) 단어는 더 고치지 않는다(설계상 의도). ③실제 마이크·전역 단축키·합성 타이핑은 헤드리스 검증 불가 → 순수 로직만 단위 테스트, 전체 흐름은 사용자 실사용. ④기본 입력 장치가 불량/점유면 캡처가 멈출 수 있음(별도 이슈 — 좋은 마이크를 기본으로).
```
