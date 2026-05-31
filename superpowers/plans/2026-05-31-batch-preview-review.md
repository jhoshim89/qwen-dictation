# 긴 말 받아쓰기 미리보기 + 키보드 선택(보내기/입력/취소) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 긴 말(오른쪽 Cmd 토글, batch)을 받아쓴 뒤 텍스트창에 바로 넣지 않고, 화면 위쪽(음량막대 자리)에서 창이 아래로 늘어나며 받아쓴 글을 보여준다. 사용자가 키보드로 결정한다 — Enter=붙여넣고 전송, 다른 키=붙여넣기만(수정용), Esc=취소(아무것도 안 함).

**Architecture:** 결정 로직을 순수 함수 `decide_review_action(key)` 로 분리해 rumps/AppKit 없이 단위 테스트한다. 배치 받아쓰기 결과를 곧장 `paste_text` 하던 흐름을, "결과를 보관하고 메인스레드에 리뷰 요청을 거는" 흐름으로 바꾼다(`StatusBarApp.request_review(text)`). 메인스레드 타이머(`_tick_overlay`)가 리뷰 상태를 보고 오버레이를 막대(녹음중) ↔ 리뷰 패널(결과+안내) 로 전환한다. 리뷰 중에는 임시 pynput 키 리스너로 Enter/Esc/기타를 받아 결정한다. `hud_overlay.DictationOverlay` 에 `show_review(text)` 를 추가해 패널이 아래로 커지고 받아쓴 글을 그린다.

**Tech Stack:** Python 3.11, PyObjC/AppKit(`hud_overlay.py`), pynput(키 입력), rumps(메뉴바 타이머). 테스트 pytest. `whisper-dictation.py` 는 하이픈이라 importlib 로드.

---

## 배경: 현재 흐름과 무엇을 바꾸나 (실측)

- `Recorder._run_batch_transcription`(whisper-dictation.py:293-310): 배치 모드는 녹음 끝나면 `text = transcribe_file(...)` 후 **즉시** `paste_text(text, submit=(mode==MODE_BATCH_SUBMIT))` 한다. 이걸 "바로 붙여넣기" 대신 "리뷰 요청"으로 바꾼다.
- `paste_text(text, submit=False)`(whisper-dictation.py:123~): pbcopy 후 AppleScript로 붙여넣기(+submit이면 Enter). 이 함수는 그대로 재사용 — 리뷰 결정 후 호출.
- `hud_overlay.DictationOverlay`(hud_overlay.py): 화면 위쪽 NSPanel(가로 300, 높이 46). `show()/hide()/update(level, elapsed)`. 여기에 리뷰 패널 표시(`show_review(text)`)와 크기 변경을 추가.
- `StatusBarApp._tick_overlay`(whisper-dictation.py:~460): 0.15초마다 메인스레드에서 `started` 면 막대 update+show, 아니면 hide. 여기에 "리뷰 대기" 상태 분기를 추가.
- 단축키: 오른쪽 Cmd 토글 = batch_paste (이미 구현됨, `MultiHotkeyListener`). 오른쪽 Option 홀드 = streaming(바로 입력, 변경 없음).

**핵심 설계 결정:**
1. **streaming(짧은 말)은 리뷰 없음** — 지금처럼 바로 타이핑. 리뷰는 batch 결과에만.
2. **batch_submit(자동전송) 모드는 그대로 둠** — 메뉴/대시보드에서 고르면 리뷰 없이 바로 전송. 단축키(오른쪽 Cmd)는 batch_paste→리뷰 경로를 쓴다. 즉 "단축키로 받아쓴 긴 말"은 항상 리뷰를 거친다.
3. **리뷰 결정은 키보드**: Enter=전송, Esc=취소, 그 외 키=붙여넣기만. 순수 함수로 분리해 테스트.
4. 리뷰 중 텍스트는 이미 `pbcopy` 로 클립보드에 올려둔다(붙여넣기만 선택 시 사용자가 Cmd+V 도 가능). 단 자동 붙여넣기는 결정 시 `paste_text` 로 수행.

**테스트 경계:** AppKit 패널·rumps 타이머·전역 키 입력은 헤드리스 불안정 → **`decide_review_action` 순수 함수와 리뷰 상태 머신만 단위 테스트**, 나머지(패널 그리기, 실제 붙여넣기)는 사용자 실행으로 검증.

---

## File Structure

- **Modify** `whisper-dictation.py`:
  - 신규 순수 함수 `decide_review_action(key)` → `"send" | "insert" | "cancel" | None`.
  - `StatusBarApp` 에 리뷰 상태: `pending_review_text`, `request_review(text)`, `resolve_review(action)`.
  - `_tick_overlay` 에 리뷰 분기(패널을 리뷰 모드로).
  - `Recorder._run_batch_transcription`: 단축키 경로면 `paste_text` 대신 `app.request_review(text)`.
  - 리뷰 중 임시 키 리스너 연결(시작 시 pynput 리스너 일시 동작).
- **Modify** `hud_overlay.py`: `DictationOverlay.show_review(text)` + 패널 리사이즈/텍스트 그리기, `hide()` 에서 원래 크기 복귀.
- **Test** `test_review_decision.py` (순수 함수), `test_review_state.py` (상태 머신, FakeApp).

---

## Task 1: 리뷰 결정 순수 함수 (decide_review_action)

키 입력을 받아 행동을 정하는 순수 함수. rumps/AppKit 없이 완전 테스트.

**Files:**
- Modify: `whisper-dictation.py` (모듈 최상위 함수로 추가 — `paste_text` 정의 근처, 클래스들보다 위)
- Test: `test_review_decision.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# test_review_decision.py
import importlib.util
from pynput import keyboard


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_enter_means_send():
    wd = _load()
    assert wd.decide_review_action(keyboard.Key.enter) == "send"


def test_esc_means_cancel():
    wd = _load()
    assert wd.decide_review_action(keyboard.Key.esc) == "cancel"


def test_letter_key_means_insert():
    wd = _load()
    assert wd.decide_review_action(keyboard.KeyCode(char="a")) == "insert"


def test_space_means_insert():
    wd = _load()
    assert wd.decide_review_action(keyboard.Key.space) == "insert"


def test_pure_modifier_is_ignored():
    wd = _load()
    # 수정키 단독(shift/cmd 등)은 결정으로 치지 않는다 → None
    assert wd.decide_review_action(keyboard.Key.shift) is None
    assert wd.decide_review_action(keyboard.Key.cmd) is None
    assert wd.decide_review_action(keyboard.Key.cmd_r) is None
    assert wd.decide_review_action(keyboard.Key.alt) is None
    assert wd.decide_review_action(keyboard.Key.ctrl) is None
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/python -m pytest test_review_decision.py -v`
Expected: FAIL — `AttributeError: module 'wd' has no attribute 'decide_review_action'`

- [ ] **Step 3: 구현 — decide_review_action 추가**

`whisper-dictation.py` 의 `paste_text` 함수 정의 바로 위(또는 바로 아래, 최상위 함수 영역)에 추가:
```python
# 리뷰 패널에서 누른 키 → 행동 결정.
_REVIEW_IGNORED_KEYS = {
    keyboard.Key.shift, keyboard.Key.shift_r,
    keyboard.Key.cmd, keyboard.Key.cmd_r,
    keyboard.Key.alt, keyboard.Key.alt_r,
    keyboard.Key.ctrl, keyboard.Key.ctrl_r,
    keyboard.Key.caps_lock, keyboard.Key.cmd_l, keyboard.Key.alt_l,
    getattr(keyboard.Key, "fn", None),
}


def decide_review_action(key):
    """리뷰 중 눌린 키로 행동을 정한다.

    Enter → "send"(붙여넣고 전송), Esc → "cancel"(아무것도 안 함),
    그 외 일반 키 → "insert"(붙여넣기만). 수정키 단독은 무시(None).
    """
    if key == keyboard.Key.enter:
        return "send"
    if key == keyboard.Key.esc:
        return "cancel"
    if key in _REVIEW_IGNORED_KEYS:
        return None
    return "insert"
```

- [ ] **Step 4: 통과 확인**

Run: `./venv/bin/python -m pytest test_review_decision.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py test_review_decision.py
git commit -m "feat: decide_review_action — Enter=send, Esc=cancel, other=insert, modifiers ignored

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 리뷰 상태 머신 (StatusBarApp.request_review / resolve_review)

배치 결과를 보관하고, 결정에 따라 붙여넣기/전송/취소를 수행하는 상태 머신. start_app/stop_app 같은 rumps 호출은 건드리지 않는 순수 상태 + paste 호출만 분리해 FakeApp 으로 테스트.

**Files:**
- Modify: `whisper-dictation.py` (`StatusBarApp` 에 상태/메서드 추가; `paste_text` 를 주입 가능하게 모듈 함수로 호출)
- Test: `test_review_state.py`

설계: `request_review(text)` 는 `pending_review_text` 에 보관하고 `review_active=True` 로 둔다(실제 패널/리스너는 _tick_overlay/Task4에서). `resolve_review(action)` 는:
- `"send"` → `paste_text(text, submit=True)` 후 상태 초기화
- `"insert"` → `paste_text(text, submit=False)` 후 상태 초기화
- `"cancel"` → 아무 것도 안 하고 상태 초기화
테스트에서는 `paste_text` 를 monkeypatch 해 호출만 검증.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# test_review_state.py
import importlib.util


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeApp:
    """StatusBarApp 의 리뷰 관련 부분만 흉내내기 위해, 실제 메서드를 빌려 쓴다."""
    pass


def _make_app(wd):
    # rumps.App 를 인스턴스화하지 않고 리뷰 메서드만 가진 객체에 바인딩.
    app = FakeApp()
    app.pending_review_text = None
    app.review_active = False
    # 실제 함수를 언바운드로 빌려 FakeApp 에 붙인다.
    app.request_review = wd.StatusBarApp.request_review.__get__(app, FakeApp)
    app.resolve_review = wd.StatusBarApp.resolve_review.__get__(app, FakeApp)
    return app


def test_request_review_stores_text(monkeypatch):
    wd = _load()
    app = _make_app(wd)
    app.request_review("hello world")
    assert app.review_active is True
    assert app.pending_review_text == "hello world"


def test_resolve_send_calls_paste_with_submit(monkeypatch):
    wd = _load()
    calls = []
    monkeypatch.setattr(wd, "paste_text", lambda text, submit=False: calls.append((text, submit)))
    app = _make_app(wd)
    app.request_review("보낼 글")
    app.resolve_review("send")
    assert calls == [("보낼 글", True)]
    assert app.review_active is False
    assert app.pending_review_text is None


def test_resolve_insert_calls_paste_without_submit(monkeypatch):
    wd = _load()
    calls = []
    monkeypatch.setattr(wd, "paste_text", lambda text, submit=False: calls.append((text, submit)))
    app = _make_app(wd)
    app.request_review("고칠 글")
    app.resolve_review("insert")
    assert calls == [("고칠 글", False)]
    assert app.review_active is False


def test_resolve_cancel_does_not_paste(monkeypatch):
    wd = _load()
    calls = []
    monkeypatch.setattr(wd, "paste_text", lambda text, submit=False: calls.append((text, submit)))
    app = _make_app(wd)
    app.request_review("버릴 글")
    app.resolve_review("cancel")
    assert calls == []
    assert app.review_active is False
    assert app.pending_review_text is None


def test_resolve_when_not_active_is_noop(monkeypatch):
    wd = _load()
    calls = []
    monkeypatch.setattr(wd, "paste_text", lambda text, submit=False: calls.append((text, submit)))
    app = _make_app(wd)
    app.review_active = False
    app.pending_review_text = None
    app.resolve_review("send")
    assert calls == []
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/python -m pytest test_review_state.py -v`
Expected: FAIL — `AttributeError: type object 'StatusBarApp' has no attribute 'request_review'`

- [ ] **Step 3: 구현 — StatusBarApp 에 상태/메서드 추가**

(a) `StatusBarApp.__init__` 안, 다른 상태 초기화들 옆(예: `self.started = False` 근처)에 추가:
```python
        self.pending_review_text = None
        self.review_active = False
```

(b) `begin_session` 메서드 근처(클래스 내 적당한 위치)에 두 메서드 추가:
```python
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
```
(주의: 테스트가 `wd.paste_text` 를 monkeypatch 하므로, 반드시 **모듈 전역 `paste_text`** 를 호출해야 한다 — `self.` 등으로 감싸지 말 것.)

- [ ] **Step 4: 통과 확인**

Run: `./venv/bin/python -m pytest test_review_state.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 전체 회귀 + 컴파일**

Run:
```bash
./venv/bin/python -m py_compile whisper-dictation.py
./venv/bin/python -m pytest -q
```
Expected: 컴파일 성공, 이전(30) + Task1(5) + Task2(5) = **40 passed**.

- [ ] **Step 6: 커밋**

```bash
git add whisper-dictation.py test_review_state.py
git commit -m "feat: review state machine — request_review/resolve_review(send|insert|cancel)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 오버레이에 리뷰 패널 추가 (hud_overlay.show_review)

화면 위쪽 패널을 녹음중(얇은 막대) ↔ 리뷰(아래로 커지며 받아쓴 글+안내) 로 전환.

**Files:**
- Modify: `hud_overlay.py`
- Test: 없음(AppKit 그리기는 헤드리스 불가 → import/구조만 점검 + 사용자 실행)

- [ ] **Step 1: 리뷰용 상수와 뷰 상태 추가**

`hud_overlay.py` 상단 상수에 추가(기존 `PANEL_WIDTH=300, PANEL_HEIGHT=46` 아래):
```python
REVIEW_WIDTH = 460.0
REVIEW_MIN_HEIGHT = 120.0
```

`_OverlayView` 에 리뷰 텍스트 상태와 그리기 분기를 추가한다. `initWithFrame_` 에 다음 ivar 추가:
```python
            self._review_text = None  # None 이면 막대 모드, 문자열이면 리뷰 모드
```
`setValues_` 는 그대로 두고, 리뷰용 setter 추가:
```python
        def setReviewText_(self, text):
            self._review_text = text
            self.setNeedsDisplay_(True)
```
`drawRect_` → `_draw` 의 맨 앞에 분기:
```python
        def _draw(self):
            if self._review_text is not None:
                self._draw_review()
                return
            # (이하 기존 막대 그리기 그대로)
```
그리고 `_draw_review` 메서드 추가(받아쓴 글 + 안내문구):
```python
        def _draw_review(self):
            bounds = self.bounds()
            w = bounds.size.width
            h = bounds.size.height
            # 받아쓴 글(여러 줄, 흰색)
            body_attrs = {
                NSFontAttributeName: NSFont.systemFontOfSize_(13.0),
                NSForegroundColorAttributeName: _rgb(243, 244, 246, 1.0),
            }
            body = NSString.stringWithString_(self._review_text)
            body_rect = NSMakeRect(14.0, 34.0, w - 28.0, h - 44.0)
            body.drawInRect_withAttributes_(body_rect, body_attrs)
            # 안내문구(하단, 회색)
            hint = "Enter: 전송   다른 키: 입력만   Esc: 취소"
            hint_attrs = {
                NSFontAttributeName: NSFont.boldSystemFontOfSize_(11.0),
                NSForegroundColorAttributeName: _rgb(165, 180, 252, 1.0),
            }
            hint_str = NSString.stringWithString_(hint)
            hint_str.drawAtPoint_withAttributes_(NSMakePoint(14.0, 10.0), hint_attrs)
```
(필요한 `NSFont.systemFontOfSize_`, `drawInRect_withAttributes_` 는 AppKit 기본 API. import 목록에 이미 NSFont 있음.)

- [ ] **Step 2: DictationOverlay 에 show_review / 크기 전환 추가**

`DictationOverlay` 에 메서드 추가:
```python
    def show_review(self, text):
        """리뷰 패널을 화면 위쪽에 띄운다(아래로 커지며 받아쓴 글 표시)."""
        if self._panel is None or self._view is None:
            return
        try:
            self._resize_panel(REVIEW_WIDTH, REVIEW_MIN_HEIGHT)
            self._view.setReviewText_(text)
            self._panel.orderFrontRegardless()
            self._visible = True
        except Exception as exc:
            print(f"hud_overlay: show_review error: {exc}")

    def _resize_panel(self, width, height):
        screen = NSScreen.mainScreen()
        if screen is not None:
            frame = screen.frame()
            sw, sh = frame.size.width, frame.size.height
            ox, oy = frame.origin.x, frame.origin.y
        else:
            sw, sh, ox, oy = 1440.0, 900.0, 0.0, 0.0
        x = ox + (sw - width) / 2.0
        y = oy + sh - height - TOP_OFFSET
        self._panel.setFrame_display_(NSMakeRect(x, y, width, height), True)
        self._view.setFrame_(NSMakeRect(0, 0, width, height))
```
그리고 막대 모드로 되돌릴 때를 위해 `hide()` 를 보강 — 숨길 때 리뷰 텍스트를 지우고 크기를 막대로 복귀:
```python
    def hide(self):
        if self._panel is None:
            return
        try:
            if self._view is not None:
                self._view.setReviewText_(None)
            self._resize_panel(PANEL_WIDTH, PANEL_HEIGHT)
            if self._visible:
                self._panel.orderOut_(None)
                self._visible = False
        except Exception as exc:
            print(f"hud_overlay: hide error: {exc}")
```
(주의: `setFrame_display_`, `setFrame_` 는 NSWindow/NSView 기본 API. `NSMakeRect` 이미 import.)

- [ ] **Step 3: import/컴파일 점검**

Run:
```bash
./venv/bin/python -m py_compile hud_overlay.py
./venv/bin/python -c "import hud_overlay; print('IMPORT_OK', hud_overlay.REVIEW_WIDTH)"
```
Expected: 컴파일 성공, `IMPORT_OK 460.0`. (창은 import 시 안 만들어짐 — 메인스레드 get_overlay 에서만.)

- [ ] **Step 4: 전체 테스트 회귀**

Run: `./venv/bin/python -m pytest -q`
Expected: `40 passed`(오버레이는 테스트 영향 없음).

- [ ] **Step 5: 커밋**

```bash
git add hud_overlay.py
git commit -m "feat: overlay review panel — expands downward to show transcript + key hints

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 배선 — 배치 결과를 리뷰로, 리뷰 키 입력 처리, 타이머 분기

배치 받아쓰기가 끝나면 리뷰를 요청하고, 메인스레드 타이머가 리뷰 패널을 띄우며, 임시 키 리스너가 결정을 받는다.

**Files:**
- Modify: `whisper-dictation.py` (`_run_batch_transcription`, `_tick_overlay`, 리뷰 키 리스너 연결)
- Test: 없음(통합/사용자 실행 검증 — 단위 가능한 로직은 Task1·2에서 끝)

설계 메모(스레딩): 받아쓰기는 백그라운드 스레드에서 끝난다. AppKit 패널은 메인스레드에서만 만져야 하므로, 백그라운드는 `app.request_review(text)`(plain 상태 세팅)만 하고, **메인스레드 `_tick_overlay`** 가 `review_active` 를 보고 `show_review` 를 띄운다. 키 입력은 별도 pynput 리스너로 받되, 결정 실행(`resolve_review`)은 paste(AppleScript)라서 메인스레드 강제는 불필요(서브프로세스 osascript).

- [ ] **Step 1: 배치 결과를 리뷰로 전환**

`Recorder._run_batch_transcription`(whisper-dictation.py:293-310)의
```python
            if not text:
                return
            paste_text(text, submit=(self.app.mode == MODE_BATCH_SUBMIT))
            safe_notify("Qwen Dictation", "Done", text)
```
를 다음으로 교체:
```python
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
```
(`pbcopy` 를 미리 해두면 사용자가 '입력만' 후 수동 Cmd+V 도 가능. `subprocess` 는 파일 상단에서 이미 import.)

- [ ] **Step 2: 리뷰 키 리스너를 StatusBarApp 에 추가**

`StatusBarApp` 에 리뷰용 임시 리스너 시작/정지 메서드를 추가한다. pynput 리스너는 콜백 스레드에서 돈다 — `resolve_review` 는 osascript(서브프로세스)라 안전.
`request_review` 를 보강해 리스너를 시작하도록, 그리고 결정 시 정지하도록 한다. `StatusBarApp` 에 추가:
```python
    def _start_review_listener(self):
        def on_press(key):
            action = decide_review_action(key)
            if action is None:
                return
            self.resolve_review(action)
            return False  # 리스너 종료

        self._review_listener = keyboard.Listener(on_press=on_press)
        self._review_listener.start()

    def _stop_review_listener(self):
        lis = getattr(self, "_review_listener", None)
        if lis is not None:
            try:
                lis.stop()
            except Exception:
                pass
            self._review_listener = None
```
그리고 Task2에서 만든 `request_review` 끝에 `self._start_review_listener()` 를, `resolve_review` 의 상태 초기화 직후(맨 끝)에 `self._stop_review_listener()` 를 추가한다. 즉:
```python
    def request_review(self, text):
        self.pending_review_text = text
        self.review_active = True
        self._start_review_listener()

    def resolve_review(self, action):
        if not self.review_active:
            return
        text = self.pending_review_text or ""
        self.review_active = False
        self.pending_review_text = None
        if action == "send":
            paste_text(text, submit=True)
        elif action == "insert":
            paste_text(text, submit=False)
        self._stop_review_listener()
```
주의: 이 변경으로 Task2 테스트가 깨지지 않아야 한다 — FakeApp 에는 `_start_review_listener`/`_stop_review_listener` 가 없으므로, 테스트의 `_make_app` 에 이 두 메서드도 바인딩하거나, 호출을 `getattr` 가드로 감싼다. **가드 방식 채택**(테스트 수정 불필요):
```python
        # request_review 끝
        starter = getattr(self, "_start_review_listener", None)
        if starter:
            starter()
```
```python
        # resolve_review 끝
        stopper = getattr(self, "_stop_review_listener", None)
        if stopper:
            stopper()
```
(FakeApp 인스턴스는 이 속성이 있으므로 — 클래스 메서드라 항상 존재 — 그러면 실제로 리스너를 만들려 한다. 테스트 환경에서 pynput 리스너 생성이 부담되면, 대신 `request_review`/`resolve_review` 자체는 리스너를 직접 부르지 말고 **별도 훅 메서드**로 두고 Task4에서 _tick_overlay 가 리스너를 관리하게 한다 — 아래 Step 3 참조. 더 안전하므로 Step 3 방식을 최종 채택하고, 위 가드 코드는 넣지 않는다.)

**최종 방침(혼란 방지):** Task2 의 `request_review`/`resolve_review` 는 **순수 상태/paste 만** 유지(리스너 호출 없음 — Task2 테스트 그대로 40 통과 유지). 리스너 시작/정지는 **`_tick_overlay`** 가 `review_active` 전이를 감지해 관리한다(Step 3). 위 `_start_review_listener`/`_stop_review_listener` 메서드 정의는 추가하되, 호출은 _tick_overlay 에서만 한다.

- [ ] **Step 3: _tick_overlay 에 리뷰 분기**

`StatusBarApp._tick_overlay`(whisper-dictation.py:~460)를 다음 형태로 보강한다. 기존 로직(녹음 중 막대, 아니면 hide)에 리뷰 분기를 추가하고, 리뷰 진입/이탈 시 키 리스너를 켜고 끈다:
```python
    def _tick_overlay(self, _):
        try:
            ov = hud_overlay.get_overlay()
            if self.review_active:
                # 리뷰 패널 표시 + (최초 진입시) 키 리스너 시작
                if not getattr(self, "_review_shown", False):
                    ov.show_review(self.pending_review_text or "")
                    self._start_review_listener()
                    self._review_shown = True
                return
            # 리뷰가 끝났으면 리스너 정리 + 패널 원복
            if getattr(self, "_review_shown", False):
                self._stop_review_listener()
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
```
그리고 `__init__` 에 `self._review_shown = False` 초기화를 추가(다른 상태 초기화 옆).

- [ ] **Step 4: 컴파일 + 전체 회귀**

Run:
```bash
./venv/bin/python -m py_compile whisper-dictation.py hud_overlay.py
./venv/bin/python -m pytest -q
```
Expected: 컴파일 성공, `40 passed`(Task2 테스트가 여전히 통과 — request_review/resolve_review 는 리스너를 직접 안 부름).

- [ ] **Step 5: grep 점검**

```bash
grep -n "request_review\|resolve_review\|_start_review_listener\|_stop_review_listener\|show_review\|_review_shown" whisper-dictation.py
```
Expected: `_run_batch_transcription` 에서 `request_review` 호출, `_tick_overlay` 에서 `show_review`/리스너 관리, 메서드 정의 존재.

- [ ] **Step 6: 커밋**

```bash
git add whisper-dictation.py
git commit -m "feat: wire batch result to review panel + temporary key listener for decision

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: .app 재빌드 + 실사용 검증 안내 + 문서

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: 재빌드**

Run: `bash build_app.sh 2>&1 | tail -15`
Expected: `dist/Qwen Dictation.app` 재생성, 치명적 에러 없음.

- [ ] **Step 2: 번들 실행 점검**

Run:
```bash
pkill -f "Qwen Dictation.app/Contents/MacOS" 2>/dev/null; sleep 1
( "dist/Qwen Dictation.app/Contents/MacOS/Qwen Dictation" > /tmp/qwen_rev_run.log 2>&1 & P=$!; sleep 35; kill $P 2>/dev/null )
grep -iE "error|traceback|no module|review|Dashboard|Initializing" /tmp/qwen_rev_run.log | head -20
pkill -f "Qwen Dictation.app/Contents/MacOS" || true
```
Expected: traceback 없음, "Settings Dashboard background server started" 보임.

- [ ] **Step 3: README 갱신**

`README.md` 의 Hotkeys 섹션에 리뷰 동작을 추가:
```markdown
### Long dictation review (right Command)

After a long (batch) dictation via right Command, the result is NOT inserted
immediately. A review panel expands from the top of the screen showing the
transcript. Decide with the keyboard:

- **Enter** → paste into the focused field and press Return (send)
- **any other key** → paste only (so you can edit, then send yourself)
- **Esc** → cancel (nothing is inserted; text stays on the clipboard)
```

- [ ] **Step 4: CLAUDE.md 갱신**

`CLAUDE.md` 에 한 줄: 단축키 배치(오른쪽 Cmd)는 결과를 곧장 붙여넣지 않고 화면 위쪽 리뷰 패널로 보여주며 키보드로 결정(Enter=전송/기타=입력만/Esc=취소). batch_submit 모드(메뉴)는 여전히 리뷰 없이 바로 전송.

- [ ] **Step 5: 커밋**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document long-dictation review panel and keyboard decisions

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: 사용자 실사용 안내(자동화 불가 부분)**

사용자에게 안내:
> 새 앱을 우클릭→열기. 오른쪽 Cmd 한 번 눌러 긴 말 → 다시 눌러 멈춤 → 화면 위쪽에 받아쓴 글 패널이 뜸 → Enter(전송)/다른 키(입력만)/Esc(취소) 확인. 짧은 말은 오른쪽 Option 홀드(바로 입력) 그대로.

---

## Self-Review (작성자 점검)

**1. 스펙 커버리지 (사용자 확정):**
- 1번 짧은 말 바로 입력 → 오른쪽 Option 홀드 streaming, 변경 없음 ✓
- 2번 긴 말: 받아쓰되 바로 입력 안 하고 보여줌 → `request_review` + `show_review` (화면 위쪽 패널, 음량막대 자리) ✓
- 보고 나서 결정: 바로 보내기 vs 입력만 → `decide_review_action`/`resolve_review`: Enter=send, 기타=insert, Esc=cancel ✓
- 키보드로 선택 → 임시 pynput 리스너 + decide_review_action ✓
- 화면 위쪽(음량막대 자리), 안 가리게 아래로 확장 → `_resize_panel` 로 막대↔리뷰 전환 ✓

**2. 플레이스홀더 스캔:** 코드 스텝 전부 실제 코드. Task4 의 스레딩/리스너 관리 방침을 "최종 방침"으로 못박아 모호함 제거(리스너는 _tick_overlay 가 관리, request/resolve 는 순수). ✓

**3. 타입/이름 일치:** `decide_review_action`(Task1) → Task4 리스너에서 사용. `request_review/resolve_review/pending_review_text/review_active`(Task2) → Task4 _tick_overlay·_run_batch_transcription 에서 사용. `show_review/_resize_panel/REVIEW_WIDTH/REVIEW_MIN_HEIGHT/setReviewText_`(Task3) → Task4 에서 호출. `_review_shown`/`_start_review_listener`/`_stop_review_listener` 일관. paste_text 모듈 전역 호출(monkeypatch 호환) ✓.

**알려진 한계(실행자 인지):** ①AppKit 패널 그리기·전역 키 입력·실제 붙여넣기는 헤드리스 검증 불가 → 순수 로직(Task1·2)만 단위 테스트, 나머지는 사용자 실행. ②리뷰 중 누른 그 키 자체는 포커스된 앱에도 들어갈 수 있음(예: 'insert' 트리거로 'a' 누르면 텍스트창에 'a'가 먼저 갈 수 있음) — 1차 구현은 단순 우선, 실사용에서 거슬리면 리스너에서 그 키를 suppress 하는 후속 작업으로 다룬다(YAGNI). ③batch_submit(메뉴 선택)은 리뷰 우회로 의도적으로 남김.
