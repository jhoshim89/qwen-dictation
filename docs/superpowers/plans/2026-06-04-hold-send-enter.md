# 홀드 키 떼면 자동 엔터 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 홀드 키를 떼면 받아쓴 마지막 글자까지 입력된 뒤 자동으로 Enter를 보내며, 설정에서 켜고 끌 수 있게 한다(기본 켜짐).

**Architecture:** 기존 `edit_interrupt_mode` 설정과 동일한 경로로 `hold_send_enter` 불리언 설정을 추가한다. 홀드 해제 종료(`finalize=True`)일 때만 `Recorder`에 `send_enter` 플래그를 전달하고, 스트리밍 루프가 마지막 글자를 타이핑한 직후 Enter를 press/release 한다. 토글 종료·수동 편집 종료·자동 종료·설정 꺼짐에서는 보내지 않는다.

**Tech Stack:** Python, pynput(keyboard.Controller), Flask 대시보드, pytest.

---

## File Structure

- `app_config.py` — `DEFAULTS`에 `hold_send_enter: True` 추가.
- `whisper-dictation.py` — `Recorder`(플래그·Enter 전송), `StatusBarApp`(설정 속성·`stop_app` 인자), `MultiHotkeyListener._end`(홀드 해제 시 전달).
- `dashboard.py` — `/api/config` GET/POST에 `hold_send_enter` 포함.
- `templates/dashboard.html` — 고급 설정 UI 추가.
- `test_app_config.py`, `test_multi_hotkey.py`, `test_streaming.py` — 테스트.

---

## Task 1: 설정 기본값 추가 (app_config)

**Files:**
- Modify: `app_config.py` (`DEFAULTS`)
- Test: `test_app_config.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`test_app_config.py`의 `test_defaults_only_have_live_settings`를 아래로 교체한다(키 집합과 기본값에 `hold_send_enter` 추가):

```python
def test_defaults_only_have_live_settings():
    assert set(app_config.DEFAULTS) == {
        "language", "max_time", "input_device", "hold_key", "toggle_key",
        "min_volume", "edit_interrupt_mode", "max_time_zero_migrated",
        "hold_send_enter",
    }
    assert app_config.DEFAULTS["max_time"] == 300
    assert app_config.DEFAULTS["min_volume"] == 35
    assert app_config.DEFAULTS["edit_interrupt_mode"] == "continue"
    assert app_config.DEFAULTS["hold_send_enter"] is True
```

그리고 라운드트립 테스트를 추가한다(파일 끝에):

```python
def test_hold_send_enter_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "config_path", lambda: str(tmp_path / "config.json"))
    app_config.save_config({"hold_send_enter": False})
    assert app_config.load_config()["hold_send_enter"] is False
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `./venv/bin/pytest test_app_config.py -q`
Expected: FAIL (`hold_send_enter` 키 없음)

- [ ] **Step 3: 최소 구현**

`app_config.py`의 `DEFAULTS` 딕셔너리에 한 줄 추가한다:

```python
    "hold_send_enter": True,
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `./venv/bin/pytest test_app_config.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app_config.py test_app_config.py
git commit -m "feat: add hold_send_enter setting default (on)"
```

---

## Task 2: Recorder — Enter 전송 플래그와 전송 로직

**Files:**
- Modify: `whisper-dictation.py` (`Recorder.__init__`, `Recorder.start`, `Recorder.stop`, `Recorder._stream_loop`, 새 `Recorder._send_enter`)
- Test: `test_streaming.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`test_streaming.py` 파일 끝에 추가한다. (이 파일이 `whisper-dictation.py`를 어떻게 import 하는지 먼저 확인하고 동일한 로더를 쓴다. 없으면 아래 `_load()`를 파일 상단에 추가.)

```python
import importlib.util


def _load_wd():
    spec = importlib.util.spec_from_file_location("wd_stream", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeKeyboard:
    def __init__(self):
        self.events = []

    def press(self, key):
        self.events.append(("press", key))

    def release(self, key):
        self.events.append(("release", key))


class _FakeTranscriber:
    def __init__(self):
        self.pykeyboard = _FakeKeyboard()


def _make_recorder(wd):
    rec = wd.Recorder(_FakeTranscriber(), app=None)
    return rec


def test_stop_sets_send_enter_only_when_finalize_and_send_enter():
    wd = _load_wd()
    from pynput import keyboard

    rec = _make_recorder(wd)
    rec.stop(finalize=True, send_enter=True)
    assert rec.send_enter_on_stop is True

    rec.stop(finalize=False, send_enter=True)
    assert rec.send_enter_on_stop is False

    rec.stop(finalize=True, send_enter=False)
    assert rec.send_enter_on_stop is False


def test_stream_loop_sends_enter_when_flag_set(monkeypatch):
    wd = _load_wd()
    from pynput import keyboard

    rec = _make_recorder(wd)
    rec.recording = False              # 루프 본문 건너뜀
    rec.finalize_on_stop = True
    rec.send_enter_on_stop = True
    monkeypatch.setattr(rec, "_stream_tick", lambda *a, **k: None)  # 받아쓰기 틱 무력화
    monkeypatch.setattr(wd.dictation_history, "add_history", lambda *_: None)

    rec._stream_loop("ko")

    kb = rec.transcriber.pykeyboard
    assert ("press", keyboard.Key.enter) in kb.events
    assert ("release", keyboard.Key.enter) in kb.events


def test_stream_loop_no_enter_when_flag_unset(monkeypatch):
    wd = _load_wd()

    rec = _make_recorder(wd)
    rec.recording = False
    rec.finalize_on_stop = True
    rec.send_enter_on_stop = False
    monkeypatch.setattr(rec, "_stream_tick", lambda *a, **k: None)
    monkeypatch.setattr(wd.dictation_history, "add_history", lambda *_: None)

    rec._stream_loop("ko")

    assert rec.transcriber.pykeyboard.events == []
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `./venv/bin/pytest test_streaming.py -q`
Expected: FAIL (`send_enter_on_stop` 속성/인자 없음)

- [ ] **Step 3: 최소 구현**

`whisper-dictation.py` `Recorder.__init__`에서 `self.self_type_guard_until = 0.0` 다음 줄에 추가:

```python
        self.send_enter_on_stop = False
```

`Recorder.start`에서 `self.finalize_on_stop = True` 다음 줄에 추가:

```python
        self.send_enter_on_stop = False
```

`Recorder.stop`을 다음으로 교체:

```python
    def stop(self, finalize=True, send_enter=False):
        # 녹음 루프(_record_impl)가 self.recording=False 를 보고 스스로 종료/정리한다.
        self.finalize_on_stop = bool(finalize)
        # 홀드 해제로 정상 종료할 때만 마지막 글자 입력 뒤 Enter 를 보낸다.
        self.send_enter_on_stop = bool(send_enter and finalize)
        self.recording = False
        audio_level.clear_level()
```

`Recorder`에 새 메서드 추가(`_stream_loop` 바로 위 등 적당한 위치):

```python
    def _send_enter(self):
        """마지막 글자까지 입력된 뒤 Enter 를 보낸다(홀드 떼면 자동 전송)."""
        # 합성 Enter 가 수동 편집으로 오인되지 않도록 가드 시각을 잠깐 세운다.
        self.self_type_guard_until = time.time() + 0.5
        try:
            time.sleep(0.05)  # 직전 타이핑 합성 이벤트 flush
            kb = self.transcriber.pykeyboard
            kb.press(keyboard.Key.enter)
            kb.release(keyboard.Key.enter)
        except Exception as exc:
            print(f"send enter error: {exc}")
```

`_stream_loop` 끝부분을 다음으로 교체(`dictation_history.add_history` 뒤에 Enter 전송 추가):

```python
        if self.finalize_on_stop:
            try:
                self._stream_tick(language, allow_stopped=True)
            except Exception as exc:
                print(f"Streaming final tick error: {exc}")
        dictation_history.add_history(self.last_typed)
        if self.send_enter_on_stop:
            self._send_enter()
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `./venv/bin/pytest test_streaming.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py test_streaming.py
git commit -m "feat: Recorder sends Enter after final tick on hold release"
```

---

## Task 3: 홀드 해제 시 stop_app 으로 send_enter 전달

**Files:**
- Modify: `whisper-dictation.py` (`MultiHotkeyListener._end`, `StatusBarApp.stop_app`, `StatusBarApp._apply_saved_config`, `StatusBarApp.current_config`)
- Test: `test_multi_hotkey.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`test_multi_hotkey.py`의 `FakeApp.stop_app`을 `send_enter`까지 기록하도록 교체하고, 기존 `FakeApp`에 기본 속성을 추가한다:

```python
class FakeApp:
    def __init__(self):
        self.started = False
        self.hold_send_enter = False
        self.log = []

    def start_app(self, _):
        self.started = True
        self.log.append(("start", True))

    def stop_app(self, _, finalize=True, send_enter=False):
        self.started = False
        self.log.append(("stop", finalize, send_enter))
```

기존 단언들의 `("stop", X)` 튜플을 `("stop", X, False)`로 갱신한다. 영향 테스트:
`test_manual_edit_stop_ends_session_without_final_tick`,
`test_enter_not_treated_as_manual_edit`,
`test_hold_cmd_starts_streaming_and_release_stops`,
`test_toggle_alt_starts_streaming_and_repress_stops`,
`test_toggle_enter_stops_without_final_tick_and_enter_keeps_flowing`,
`test_hold_combo_starts_after_last_key_and_stops_on_release`,
`test_toggle_combo_fires_once_until_released`.

예: `test_hold_cmd_starts_streaming_and_release_stops`의 마지막 단언을
`assert app.log == [("start", True), ("stop", True, False)]`로 바꾼다.
(`EditApp`은 `FakeApp`을 상속하므로 `("stop", False)` → `("stop", False, False)`)

새 테스트를 파일 끝에 추가한다:

```python
def test_hold_release_sends_enter_when_enabled():
    wd = _load()
    app = FakeApp()
    app.hold_send_enter = True
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.cmd_r)
    lis.on_key_release(keyboard.Key.cmd_r)
    assert app.log == [("start", True), ("stop", True, True)]


def test_hold_release_no_enter_when_disabled():
    wd = _load()
    app = FakeApp()
    app.hold_send_enter = False
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.cmd_r)
    lis.on_key_release(keyboard.Key.cmd_r)
    assert app.log == [("start", True), ("stop", True, False)]


def test_toggle_stop_never_sends_enter_even_when_enabled():
    wd = _load()
    app = FakeApp()
    app.hold_send_enter = True
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_press(keyboard.Key.alt_r)  # 다시 눌러 종료
    assert app.log == [("start", True), ("stop", True, False)]


def test_manual_edit_stop_never_sends_enter_even_when_enabled():
    wd = _load()
    app = EditApp("stop")
    app.hold_send_enter = True
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.cmd_r)            # 홀드 시작
    lis.on_key_press(keyboard.KeyCode(char="x"))    # 수동 편집 → 종료
    assert app.log == [("start", True), ("stop", False, False)]
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `./venv/bin/pytest test_multi_hotkey.py -q`
Expected: FAIL (`_end`가 아직 `send_enter`를 전달하지 않음)

- [ ] **Step 3: 최소 구현**

`whisper-dictation.py` `MultiHotkeyListener._end`를 교체:

```python
    def _end(self, trigger, finalize=True):
        if self.active_trigger != trigger:
            return
        send_enter = (
            trigger == "hold"
            and finalize
            and bool(getattr(self.app, "hold_send_enter", False))
        )
        dispatch_app(self.app, self.app.stop_app, None, finalize, send_enter)
        self.active_trigger = None
```

`StatusBarApp.stop_app` 시그니처와 본문 호출을 교체:

```python
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
```

`StatusBarApp._apply_saved_config`에서 `edit_interrupt_mode` 처리 뒤에 추가:

```python
        self.hold_send_enter = bool(cfg.get("hold_send_enter", True))
```

`StatusBarApp.current_config`의 반환 딕셔너리에 추가:

```python
            "hold_send_enter": getattr(self, "hold_send_enter", True),
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `./venv/bin/pytest test_multi_hotkey.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py test_multi_hotkey.py
git commit -m "feat: pass send_enter on hold release through stop_app"
```

---

## Task 4: 대시보드 설정 노출 (백엔드 + UI)

**Files:**
- Modify: `dashboard.py` (`/api/config` GET, POST)
- Modify: `templates/dashboard.html`
- Test: `test_dashboard_paths.py` (해당 파일에 config GET/POST 테스트가 있으면 거기에, 없으면 수동 검증)

- [ ] **Step 1: dashboard.py GET 응답에 값 추가**

`dashboard.py`에서 config 응답을 만드는 부분(약 64행, `"toggle_key"`/`"edit_interrupt_mode"` 주변)에 추가:

```python
        "hold_send_enter": bool(getattr(app_instance, 'hold_send_enter', True)),
```

- [ ] **Step 2: dashboard.py POST 처리에 값 반영**

`edit_interrupt_mode` 처리 블록(약 92-94행) 뒤에 추가:

```python
        if 'hold_send_enter' in data:
            app_instance.hold_send_enter = bool(data['hold_send_enter'])
```

(이 블록은 기존 `if hasattr(app_instance, "save_settings"): app_instance.save_settings()` **앞**에 있어야 저장에 포함된다.)

- [ ] **Step 3: dashboard.html UI 추가**

`templates/dashboard.html`의 고급 설정에서 "받아쓰기 도중 손대면" `<select>`와 그 `<p class="hint">` 바로 뒤에 항목을 추가한다. `edit-interrupt-mode` 셀렉트 직후, `max-time` 라벨 앞에 삽입:

```html
<label for="hold-send-enter">홀드 키 떼면 자동 엔터</label><select id="hold-send-enter" onchange="updateConfig()"><option value="on">켬 — 손 떼면 마지막 글자까지 입력 후 엔터</option><option value="off">끔</option></select><p class="hint">오른쪽 Cmd 같은 홀드 키로 말한 뒤 손을 떼면 자동으로 엔터를 눌러 전송합니다. 토글 키에는 적용되지 않습니다.</p>
```

`fetchConfig` 함수에서 `edit-interrupt-mode` 값을 채우는 줄 뒤에 추가:

```javascript
document.getElementById("hold-send-enter").value=(d.hold_send_enter===false)?"off":"on";
```

`updateConfig` 함수의 POST body 객체에 키를 추가한다(`edit_interrupt_mode:...` 뒤):

```javascript
hold_send_enter:document.getElementById("hold-send-enter").value==="on"
```

- [ ] **Step 4: 컴파일 확인**

Run: `./venv/bin/python -m py_compile dashboard.py`
Expected: 출력 없음(성공)

- [ ] **Step 5: 커밋**

```bash
git add dashboard.py templates/dashboard.html
git commit -m "feat: dashboard toggle for hold-release auto Enter"
```

---

## Task 5: 전체 검증

**Files:** 없음(검증만)

- [ ] **Step 1: 전체 컴파일**

Run: `./venv/bin/python -m py_compile whisper-dictation.py dashboard.py dictation_history.py hud_overlay.py`
Expected: 출력 없음

- [ ] **Step 2: 전체 테스트**

Run: `./venv/bin/pytest -q`
Expected: 전부 PASS

- [ ] **Step 3: 수동 검증(앱 실행)**

`./run.sh`로 실행 → 대시보드(http://127.0.0.1:5001) 고급 설정에 "홀드 키 떼면 자동 엔터" 항목 확인. 켬 상태에서 채팅창에 포커스 두고 홀드 키로 한 문장 말한 뒤 손을 떼면 → 마지막 글자까지 입력된 뒤 엔터로 전송되는지 확인. 끔으로 바꾸면 엔터가 안 나가는지 확인. 토글 키로 말하면 엔터가 안 나가는지 확인.

- [ ] **Step 4: 커밋(필요 시)**

검증만 했으면 커밋 없음.

---

## Self-Review 결과

- **스펙 커버리지**: 설정 추가(Task 1, 3, 4), 홀드 해제 시 마지막 글자 후 Enter(Task 2), 예외 경우 — 토글/수동편집/자동종료/꺼짐(Task 2의 `send_enter and finalize`, Task 3의 트리거·설정 조건과 테스트) 모두 태스크에 매핑됨.
- **플레이스홀더**: 없음. 모든 코드 단계에 실제 코드 포함.
- **타입 일관성**: `send_enter`(stop_app/Recorder.stop), `send_enter_on_stop`(Recorder 속성), `hold_send_enter`(설정/앱 속성) 이름이 모든 태스크에서 일치.
