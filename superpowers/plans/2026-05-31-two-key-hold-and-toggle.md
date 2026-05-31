# 단일키 2개로 홀드/토글 받아쓰기 (오른쪽 Option·Cmd) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 단축키 하나씩만 눌러 두 가지 받아쓰기를 쓴다 — 오른쪽 Option은 누르는 동안만 녹음(홀드)하는 짧은 말용 스트리밍, 오른쪽 Cmd는 눌러서 시작/정지(토글)하는 긴 말용 배치(붙여넣고 멈춤; 전송은 사용자가 결과를 보고 직접). 자동 Enter 전송(batch_submit)은 단축키에서 제외한다.

**Architecture:** 새 리스너 클래스 `MultiHotkeyListener` 가 두 단일 오른쪽 수정키를 (모드, 제스처)에 매핑한다. 동시에 하나의 트리거만 활성(`active_trigger`)으로 두어 키 충돌을 막는다. 녹음 시작은 `StatusBarApp.begin_session(mode)` 로 일원화한다 — 이번 녹음에만 모드를 적용하고(저장 안 함, 영속 기본값 보존), 기존 `start_app`/`stop_app` 을 재사용한다. 리스너는 rumps 없이 단위 테스트 가능하므로 `FakeApp` 으로 검증한다. batch_submit 모드 자체는 코드에 남겨 메뉴/대시보드로는 여전히 선택 가능하되, 단축키에는 배정하지 않는다.

**Tech Stack:** Python 3.11, pynput(keyboard.Key.alt_r/cmd_r), rumps(메뉴바). 테스트 pytest. `whisper-dictation.py` 는 하이픈이라 importlib 로 로드.

---

## 배경: 현재 동작과 무엇을 바꾸나

- 현재 `GlobalKeyListener` 는 키 조합(`cmd_l+alt`)으로 **toggle만** 한다. 단일키도 토글. `DoubleCommandKeyListener` 는 오른쪽 Cmd 더블탭.
- 모드(streaming/batch_paste/batch_submit)는 메뉴/대시보드로만 바꾸고, 단축키는 모드를 안 건드린다.
- **홀드(누르는 동안만 녹음) 제스처는 없다.**
- `Recorder` 는 시작 시 `self.app.mode` 를 읽어 동작을 정한다(streaming=실시간, 그 외=멈춘 뒤 배치). `start_app`/`stop_app` 이 `app.started`, recorder, 타이머, 오버레이를 관리.

**원하는 매핑(사용자 확정):**
| 키(단일, 오른쪽) | 제스처 | 모드 | 용도 |
|---|---|---|---|
| Option (`alt_r`) | 홀드: 누르는 동안 녹음, 떼면 정지 | streaming | 짧은 말, 실시간 |
| Cmd (`cmd_r`) | 토글: 눌러 시작, 다시 눌러 정지 | batch_paste | 긴 말 — 붙여넣고 멈춤, 사용자가 결과 보고 직접 전송/수정 |

**왜 batch_submit(자동 Enter)을 단축키에서 뺐나(사용자 논리):** 긴 말은 모델이 문맥으로 교정하지만 완벽하지 않다. 결과를 **눈으로 본 뒤** 맞으면 직접 Enter, 틀리면 고친 뒤 Enter 하는 게 안전하다. 자동 전송은 틀린 채로 나가버릴 위험이 있어 긴 말엔 부적합. (batch_submit 모드는 코드/메뉴에는 남겨두되 단축키만 배정 안 함.)

**알려진 트레이드오프:** 오른쪽 수정키 단독 누름을 트리거로 쓴다. 보통 단축키는 왼쪽 수정키라 충돌이 드물지만, 오른쪽 Cmd/Option 을 조합키로 쓰는 습관이 있으면 의도치 않게 녹음이 켜질 수 있다(기존 `DoubleCommandKeyListener` 도 `cmd_r` 를 트리거로 썼음).

**테스트 경계:** `StatusBarApp` 은 rumps라 헤드리스 불안정 → `begin_session` 은 통합 점검으로, **리스너 로직은 `FakeApp` 으로 완전 단위 테스트**.

---

## File Structure

- **Modify** `whisper-dictation.py`:
  - 신규 클래스 `MultiHotkeyListener` (두 키 → 모드/제스처, 단일 활성 트리거).
  - `StatusBarApp.begin_session(mode)` 메서드(세션 한정 모드 적용 + start, 저장 안 함).
  - `main()` 리스너 선택을 `MultiHotkeyListener` 기본으로 교체(레거시는 플래그로 유지).
  - `parse_args` 에 `--hotkeys {multi,single,double}` 기본 `multi`.
- **Test** `test_multi_hotkey.py` — 리스너 동작 전부.

다른 파일 변경 없음.

---

## Task 1: MultiHotkeyListener (test-first, FakeApp로 완전 검증)

두 단일키를 모드/제스처에 매핑하는 리스너. rumps 없이 테스트.

**Files:**
- Modify: `whisper-dictation.py` (`DoubleCommandKeyListener` 클래스 정의 끝 — `on_key_release` 메서드 다음, 다음 최상위 `class StatusBarApp` 앞 — 에 신규 클래스 삽입)
- Test: `test_multi_hotkey.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# test_multi_hotkey.py
import importlib.util
from pynput import keyboard


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeApp:
    def __init__(self):
        self.started = False
        self.mode = None
        self.log = []

    def begin_session(self, mode):
        self.mode = mode
        self.started = True
        self.log.append(("begin", mode))

    def stop_app(self, _):
        self.started = False
        self.log.append(("stop",))


def test_hold_option_starts_streaming_and_release_stops():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    assert app.started is True
    assert app.mode == wd.MODE_STREAMING
    lis.on_key_release(keyboard.Key.alt_r)
    assert app.started is False
    assert app.log == [("begin", wd.MODE_STREAMING), ("stop",)]


def test_hold_autorepeat_does_not_restart():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)   # 시작
    lis.on_key_press(keyboard.Key.alt_r)   # auto-repeat — 무시
    assert app.log == [("begin", wd.MODE_STREAMING)]


def test_toggle_cmd_starts_batch_paste_and_repress_stops():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.cmd_r)
    assert app.started is True and app.mode == wd.MODE_BATCH_PASTE
    lis.on_key_release(keyboard.Key.cmd_r)   # 토글은 release 로 안 멈춤
    assert app.started is True
    lis.on_key_press(keyboard.Key.cmd_r)     # 다시 누르면 멈춤
    assert app.started is False
    assert app.log == [("begin", wd.MODE_BATCH_PASTE), ("stop",)]


def test_other_key_ignored_while_recording():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.cmd_r)        # toggle paste 시작
    lis.on_key_press(keyboard.Key.alt_r)        # 녹음 중 hold 키 → 무시
    assert app.mode == wd.MODE_BATCH_PASTE
    assert app.log == [("begin", wd.MODE_BATCH_PASTE)]


def test_release_of_non_owning_key_does_nothing():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.cmd_r)        # toggle 시작
    lis.on_key_release(keyboard.Key.alt_r)      # 엉뚱한 키 release
    assert app.started is True


def test_unrelated_key_does_nothing():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.KeyCode(char="a"))
    lis.on_key_release(keyboard.KeyCode(char="a"))
    assert app.started is False
    assert app.log == []
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/python -m pytest test_multi_hotkey.py -v`
Expected: FAIL — `AttributeError: module 'wd' has no attribute 'MultiHotkeyListener'`

- [ ] **Step 3: 구현 — MultiHotkeyListener 클래스 추가**

`whisper-dictation.py` 에서 `class DoubleCommandKeyListener:` 의 마지막 메서드(`on_key_release`, 약 388-389행: `def on_key_release(self, key):` / `        pass`) 다음, 그리고 `class StatusBarApp(rumps.App):`(약 392행) 앞의 빈 줄 자리에 아래 클래스를 삽입한다. `MODE_STREAMING`/`MODE_BATCH_PASTE` 상수는 파일 상단(32-34행)에 이미 정의돼 있다.

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `./venv/bin/python -m pytest test_multi_hotkey.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py test_multi_hotkey.py
git commit -m "feat: MultiHotkeyListener — right Option(hold/streaming), right Cmd(toggle/batch_paste)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: StatusBarApp.begin_session + main 배선

리스너가 호출할 `begin_session` 을 추가하고, `main()` 이 기본으로 `MultiHotkeyListener` 를 쓰게 한다.

**Files:**
- Modify: `whisper-dictation.py` (`StatusBarApp` 에 메서드 추가; `parse_args` 에 인자 추가; `main()` 리스너 선택 교체)
- Test: 없음(rumps 헤드리스 불안정 → 통합 점검 + 단위테스트 회귀)

- [ ] **Step 1: begin_session 메서드 추가**

`StatusBarApp` 의 `toggle` 메서드 정의(약 538-542행) 바로 다음에 추가한다(들여쓰기 4칸):
```python
    def begin_session(self, mode):
        """단축키가 이번 녹음에만 모드를 적용하고 시작한다(저장하지 않음).

        영속 기본 모드(app_config)는 그대로 두고, 세션 동안만 mode 를 바꾼다.
        """
        if self.started:
            return
        self.mode = mode
        self.sync_menu_state()
        self.start_app(None)
```
(주의: `set_mode` 를 쓰지 않는다 — set_mode 는 `started` 면 예외를 던지고 `save_settings()` 로 영속화한다. begin_session 은 시작 전이라 안전하고, 저장 안 해서 사용자의 기본 모드를 덮지 않는다.)

- [ ] **Step 2: parse_args 에 --hotkeys 추가**

`parse_args` 의 `parser.add_argument("--mode", ...)` 줄(약 567행) 다음에 추가:
```python
    parser.add_argument(
        "--hotkeys",
        choices=("multi", "single", "double"),
        default="multi",
        help="multi=right Option(hold)/right Cmd(toggle) single keys (default); single=-k combo; double=double right Cmd.",
    )
```

- [ ] **Step 3: main() 리스너 선택 교체**

`main()` 의 기존 줄(약 588행):
```python
    key_listener = DoubleCommandKeyListener(app) if args.k_double_cmd else GlobalKeyListener(app, args.key_combination)
```
을 다음으로 교체:
```python
    if args.k_double_cmd or args.hotkeys == "double":
        key_listener = DoubleCommandKeyListener(app)
    elif args.hotkeys == "single":
        key_listener = GlobalKeyListener(app, args.key_combination)
    else:
        key_listener = MultiHotkeyListener(app)
```
바로 다음 줄(`listener = keyboard.Listener(on_press=key_listener.on_key_press, on_release=key_listener.on_key_release)`)은 그대로 둔다 — `MultiHotkeyListener` 도 `on_key_press`/`on_key_release` 를 제공하므로 호환.

- [ ] **Step 4: 컴파일 + 단위테스트 회귀**

Run:
```bash
./venv/bin/python -m py_compile whisper-dictation.py
./venv/bin/python -m pytest -q
```
Expected: 컴파일 성공. 전체 통과(이전 24 + Task1 6 = **30 passed**).

- [ ] **Step 5: 비영속성 + 배선 점검(grep)**

```bash
grep -n "def begin_session" whisper-dictation.py
grep -n "MultiHotkeyListener(app)" whisper-dictation.py
grep -n "args.hotkeys\|--hotkeys" whisper-dictation.py
```
Expected: `begin_session` 존재, main else 분기에서 `MultiHotkeyListener(app)` 사용, `--hotkeys` 인자 정의. 그리고 `begin_session` 함수 본문(다음 `def` 전까지)에 `save_settings()` 호출이 **없음**을 눈으로 확인(세션 모드는 저장 안 함).

- [ ] **Step 6: 커밋**

```bash
git add whisper-dictation.py
git commit -m "feat: wire MultiHotkeyListener as default; add begin_session and --hotkeys flag

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: .app 재빌드 + 문서

새 단축키 동작을 번들에 반영하고 사용법을 문서화.

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: 재빌드**

Run: `bash build_app.sh 2>&1 | tail -15`
Expected: `dist/Qwen Dictation.app` 재생성, 치명적 에러 없음(새 코드는 일반 클래스라 hidden-import 불필요).

- [ ] **Step 2: 번들 실행 점검**

Run:
```bash
pkill -f "Qwen Dictation.app/Contents/MacOS" 2>/dev/null; sleep 1
( "dist/Qwen Dictation.app/Contents/MacOS/Qwen Dictation" > /tmp/qwen_hk_run.log 2>&1 & P=$!; sleep 35; kill $P 2>/dev/null )
grep -iE "error|traceback|no module|MultiHotkey|Dashboard|Initializing" /tmp/qwen_hk_run.log | head -20
pkill -f "Qwen Dictation.app/Contents/MacOS" || true
```
Expected: traceback 없음, "Settings Dashboard background server started" 보임. "not trusted" 줄은 정상.

- [ ] **Step 3: README 단축키 섹션 추가/교체**

`README.md` 에 "## Hotkeys" 섹션을 추가(기존 hotkey 설명이 있으면 교체):
```markdown
## Hotkeys (default: multi)

Press ONE key — no combos:

| Key (right side) | Gesture | Mode | Use |
|---|---|---|---|
| Right Option (⌥) | Hold while speaking, release to stop | Streaming | short phrases, live typing |
| Right Command (⌘) | Press to start, press again to stop | Batch paste | long dictation — pasted, then you review and send/edit yourself |

Long dictation is pasted but NOT auto-sent: the model edits by context but isn't
perfect, so you read the result and press Return yourself (or fix it first).
The auto-send mode (Batch paste + Enter) still exists in the menu/dashboard but
is intentionally not bound to a hotkey.

Legacy: `./run.sh --hotkeys single -k cmd_l+alt` (two-key toggle) or
`./run.sh --hotkeys double` / `--k_double_cmd` (double right Cmd).
```

- [ ] **Step 4: CLAUDE.md 갱신**

`CLAUDE.md` 의 단축키 서술에 한 줄: 기본 단축키 방식이 `MultiHotkeyListener`(오른쪽 Option=홀드/streaming, 오른쪽 Cmd=토글/batch_paste; batch_submit 은 단축키 미배정), `--hotkeys single|double` 로 레거시 선택 가능.

- [ ] **Step 5: 커밋**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document two single-key hotkeys (hold=short, toggle=long) and rebuild

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (작성자 점검)

**1. 스펙 커버리지 (사용자 확정 요구):**
- 단일키만(조합 없이) → 두 키 모두 단일 오른쪽 수정키 ✓
- 짧은 말=홀드, 실시간(streaming) → 오른쪽 Option 홀드 ✓
- 긴 말=토글, 붙여넣고 멈춤(사용자가 결과 보고 직접 전송/수정) → 오른쪽 Cmd 토글=batch_paste ✓
- 3번(자동 Enter 전송) 단축키 제외 → batch_submit 은 메뉴/대시보드에만 남김 ✓
- 홀드+토글 둘 다, 키 서로 다르게 → Option(홀드) vs Cmd(토글) ✓

**2. 플레이스홀더 스캔:** "적절히 처리" 류 없음. 모든 코드 스텝에 실제 코드. 검증은 grep/pytest 구체 명령 ✓

**3. 타입/이름 일치:** `MultiHotkeyListener(__init__, _begin, _end, on_key_press, on_key_release)` Task1 정의 → Task2 main 사용. `begin_session(mode)` Task2 정의 ↔ 리스너의 `self.app.begin_session(mode)`(Task1) 및 FakeApp 동일 시그니처. `MODE_STREAMING/MODE_BATCH_PASTE` 기존 상수. `on_key_press/on_key_release` 가 기존 `keyboard.Listener` 배선과 호환 ✓.

**알려진 한계:** ①`begin_session`/`start_app` 은 rumps라 헤드리스 단위테스트 불가 → 리스너는 FakeApp 으로 완전 검증, 실제 연동은 사용자 실행 확인. ②오른쪽 수정키 단독 트리거 충돌 가능성은 수용된 설계. ③홀드 키 auto-repeat 는 `if not self.app.started` 가드로 무해(test_hold_autorepeat_does_not_restart 로 확인).
