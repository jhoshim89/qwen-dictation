# HUD 표시 모드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 받아쓰기 인디케이터(HUD)를 알약/아이콘 고정/아이콘 커서추적 3모드로 만들고 대시보드에서 고르게 한다.

**Architecture:** `hud_overlay.py`에 순수 헬퍼(모드 정규화·좌표 클램프)와 컴팩트(원형 36px) 렌더링·모드 전환 로직을 추가한다. `whisper-dictation.py`의 0.15초 틱이 설정 변화를 감지해 `set_mode`를 호출하고, 커서 모드면 매 틱 커서로 이동시키며, 고정 모드의 드래그 위치를 폴링해 저장한다. `app_config.py`/`dashboard.py`/`templates/dashboard.html`은 기존 `domain_context` 흐름 그대로 새 설정 키를 저장·노출한다.

**Tech Stack:** Python, PyObjC/AppKit, Flask, pytest. macOS 전용.

설계 문서: `docs/superpowers/specs/2026-06-04-hud-display-modes-design.md`

---

## File Structure

- `app_config.py` — DEFAULTS에 `hud_mode`, `hud_pin_x`, `hud_pin_y` 추가.
- `hud_overlay.py` — 순수 헬퍼 `normalize_hud_mode`/`clamp_to_visible`, 아이콘 상수, `_OverlayView` 컴팩트/흐림 렌더, `DictationOverlay`의 `set_mode`/`reposition_to_cursor`/`current_origin`/`set_processing`.
- `whisper-dictation.py` — `current_config`/`_apply_saved_config`에 키 추가, `_tick_overlay`가 모드 적용·커서추적·드래그저장 담당.
- `dashboard.py` — GET/POST `/api/config`에 3개 키.
- `templates/dashboard.html` — "음성 인식" 패널에 `hud-mode` 셀렉트 + JS 연결.
- 테스트: `test_app_config.py`, `test_hud_overlay.py`, `test_dashboard_paths.py`에 추가.
- `.gitignore` — `.superpowers/` 무시.

---

## Task 1: 설정 키 추가 (app_config)

**Files:**
- Modify: `app_config.py:12-28` (DEFAULTS)
- Test: `test_app_config.py`

- [ ] **Step 1: 실패 테스트 작성** — `test_app_config.py`의 기존 `test_defaults_only_have_live_settings`를 새 키 포함하도록 교체하고, 새 테스트 2개 추가.

기존 `test_defaults_only_have_live_settings` 함수 전체를 아래로 교체:

```python
def test_defaults_only_have_live_settings():
    assert set(app_config.DEFAULTS) == {
        "language", "max_time", "input_device", "hold_key", "toggle_key",
        "min_volume", "edit_interrupt_mode", "max_time_zero_migrated",
        "hold_send_enter", "domain_context",
        "hud_mode", "hud_pin_x", "hud_pin_y",
    }
    assert app_config.DEFAULTS["max_time"] == 300
    assert app_config.DEFAULTS["min_volume"] == 35
    assert app_config.DEFAULTS["edit_interrupt_mode"] == "continue"
    assert app_config.DEFAULTS["hold_send_enter"] is True
    assert app_config.DEFAULTS["domain_context"] == ""
    assert app_config.DEFAULTS["hud_mode"] == "pill"
    assert app_config.DEFAULTS["hud_pin_x"] is None
    assert app_config.DEFAULTS["hud_pin_y"] is None
```

파일 끝에 추가:

```python
def test_hud_mode_defaults_to_pill(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "config_path", lambda: str(tmp_path / "config.json"))
    assert app_config.load_config()["hud_mode"] == "pill"


def test_hud_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "config_path", lambda: str(tmp_path / "config.json"))
    app_config.save_config({"hud_mode": "pinned", "hud_pin_x": 1380.0, "hud_pin_y": 24.0})
    cfg = app_config.load_config()
    assert cfg["hud_mode"] == "pinned"
    assert cfg["hud_pin_x"] == 1380.0
    assert cfg["hud_pin_y"] == 24.0
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/pytest test_app_config.py -q`
Expected: FAIL (KeyError/AssertionError — 새 키 없음)

- [ ] **Step 3: 최소 구현** — `app_config.py`의 DEFAULTS에서 `"domain_context": "",` 줄 바로 다음에 세 줄 추가:

```python
    # 받아쓰기 표시(HUD) 모드: "pill"(알약·기본) | "pinned"(아이콘 고정) | "cursor"(커서 추적).
    "hud_mode": "pill",
    # B(고정) 모드에서 드래그로 저장된 절대 좌표(AppKit, 좌하단 원점). None이면 기본 우하단.
    "hud_pin_x": None,
    "hud_pin_y": None,
```

- [ ] **Step 4: 통과 확인**

Run: `./venv/bin/pytest test_app_config.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app_config.py test_app_config.py
git commit -m "feat: add hud_mode and pin position config keys"
```

---

## Task 2: 순수 헬퍼 + 아이콘 상수 (hud_overlay)

**Files:**
- Modify: `hud_overlay.py` (모듈 상단, `jelly_bar_heights` 다음)
- Test: `test_hud_overlay.py`

- [ ] **Step 1: 실패 테스트 작성** — `test_hud_overlay.py` 파일 끝에 추가:

```python
def test_normalize_hud_mode_accepts_known_and_falls_back():
    assert hud_overlay.normalize_hud_mode("pill") == "pill"
    assert hud_overlay.normalize_hud_mode("pinned") == "pinned"
    assert hud_overlay.normalize_hud_mode("cursor") == "cursor"
    assert hud_overlay.normalize_hud_mode("bogus") == "pill"
    assert hud_overlay.normalize_hud_mode(None) == "pill"


def test_icon_size_is_36():
    assert hud_overlay.ICON_SIZE == 36.0


def test_clamp_to_visible_keeps_point_inside_a_screen():
    screens = [(0.0, 0.0, 1440.0, 900.0)]
    assert hud_overlay.clamp_to_visible(100.0, 100.0, 36.0, 36.0, screens) == (100.0, 100.0)


def test_clamp_to_visible_offscreen_returns_default_bottom_right():
    screens = [(0.0, 0.0, 1440.0, 900.0)]
    # 1440-36-24 = 1380, 0+24 = 24
    assert hud_overlay.clamp_to_visible(5000.0, 5000.0, 36.0, 36.0, screens) == (1380.0, 24.0)


def test_clamp_to_visible_none_returns_default():
    screens = [(0.0, 0.0, 1440.0, 900.0)]
    assert hud_overlay.clamp_to_visible(None, None, 36.0, 36.0, screens) == (1380.0, 24.0)


def test_clamp_to_visible_no_screens_returns_origin():
    assert hud_overlay.clamp_to_visible(None, None, 36.0, 36.0, []) == (0.0, 0.0)
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/pytest test_hud_overlay.py -q`
Expected: FAIL (AttributeError — `normalize_hud_mode`/`ICON_SIZE`/`clamp_to_visible` 없음)

- [ ] **Step 3: 최소 구현** — `hud_overlay.py`에서 `jelly_bar_heights` 함수 정의 다음(빈 줄 두 개 뒤, `try: import objc` 앞)에 추가:

```python
# 표시 모드와 아이콘(컴팩트) 사양. AppKit 없이도 import/테스트되도록 모듈 상단에 둔다.
HUD_MODES = ("pill", "pinned", "cursor")
ICON_SIZE = 36.0
ICON_BAR_WIDTH = 3.5
ICON_BAR_GAP = 2.5
PIN_DEFAULT_MARGIN = 24.0
CURSOR_OFFSET_X = 14.0
CURSOR_OFFSET_Y = 6.0


def normalize_hud_mode(value):
    """알 수 없는 값은 안전하게 'pill'로 떨어뜨린다."""
    return value if value in HUD_MODES else "pill"


def clamp_to_visible(x, y, width, height, screen_boxes):
    """저장된 (x, y)가 어느 화면 박스 안에 들어가면 그대로, 아니면 첫 화면(주 모니터)
    오른쪽 아래 기본 자리를 돌려준다.

    screen_boxes: (origin_x, origin_y, width, height) 튜플 리스트(visibleFrame).
    좌표계는 AppKit(좌하단 원점)."""
    if x is not None and y is not None:
        for ox, oy, sw, sh in screen_boxes:
            if ox <= x <= ox + sw - width and oy <= y <= oy + sh - height:
                return float(x), float(y)
    if screen_boxes:
        ox, oy, sw, sh = screen_boxes[0]
        return (ox + sw - width - PIN_DEFAULT_MARGIN, oy + PIN_DEFAULT_MARGIN)
    return 0.0, 0.0
```

- [ ] **Step 4: 통과 확인**

Run: `./venv/bin/pytest test_hud_overlay.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add hud_overlay.py test_hud_overlay.py
git commit -m "feat: add hud mode normalize and pin clamp helpers"
```

---

## Task 3: 컴팩트(원형) 렌더링 (_OverlayView)

**Files:**
- Modify: `hud_overlay.py` (`_OverlayView` 클래스: init, 새 세터, `_draw`)

이 작업은 AppKit 드로잉이라 자동 테스트가 아니라 `py_compile`로 문법만 검증하고 육안 확인 대상이다.

- [ ] **Step 1: init에 플래그 추가** — `_OverlayView.initWithFrame_`의 `self._label_text = "듣는 중"` 줄 다음에 두 줄 추가:

```python
            self._compact = False
            self._dimmed = False
```

- [ ] **Step 2: 세터 추가** — `setLabelText_` 메서드 정의 바로 다음에 추가:

```python
        def setCompact_(self, flag):
            self._compact = bool(flag)
            self.setNeedsDisplay_(True)

        def setDimmed_(self, flag):
            self._dimmed = bool(flag)
            self.setNeedsDisplay_(True)
```

- [ ] **Step 3: `_draw` 분기** — 기존 `_draw` 메서드 전체를 아래로 교체:

```python
        def _draw(self):
            self._draw_background()
            bounds = self.bounds()
            cy = bounds.size.height / 2.0
            heights = jelly_bar_heights(self._level)

            if self._compact:
                total = (ICON_BAR_WIDTH * 3) + (ICON_BAR_GAP * 2)
                start_x = (bounds.size.width - total) / 2.0
                alpha = 0.5 if self._dimmed else 0.94
                for index, height in enumerate(heights):
                    x = start_x + (index * (ICON_BAR_WIDTH + ICON_BAR_GAP))
                    y = cy - (height / 2.0)
                    self._draw_jelly_rect(x, y, ICON_BAR_WIDTH, height, alpha=alpha)
                return

            bar_w = 4.0
            gap = 4.0
            start_x = 14.0
            for index, height in enumerate(heights):
                x = start_x + (index * (bar_w + gap))
                y = cy - (height / 2.0)
                self._draw_jelly_rect(x, y, bar_w, height)
            self._draw_label()
```

- [ ] **Step 4: 문법 검증**

Run: `./venv/bin/python -m py_compile hud_overlay.py`
Expected: 출력 없음(성공)

- [ ] **Step 5: 기존 테스트 회귀 확인**

Run: `./venv/bin/pytest test_hud_overlay.py -q`
Expected: PASS (기존 + Task 2 테스트 모두)

- [ ] **Step 6: 커밋**

```bash
git add hud_overlay.py
git commit -m "feat: compact circular hud rendering with dim state"
```

---

## Task 4: 모드 전환·위치 로직 (DictationOverlay)

**Files:**
- Modify: `hud_overlay.py` (`DictationOverlay` 클래스)
- Test: `test_hud_overlay.py`

`set_mode`의 pill 경로는 페이크로 단위 테스트하고, pinned/cursor 경로(AppKit 프레임 조작)는 `py_compile` + 육안 확인.

- [ ] **Step 1: 페이크 확장 + 실패 테스트** — `test_hud_overlay.py`의 `_FakePanel`/`_FakeView`에 메서드를 추가하고 테스트를 추가.

`_FakePanel`에 메서드 추가(클래스 본문 안):

```python
    def setIgnoresMouseEvents_(self, flag):
        self.ignores_mouse = flag

    def setMovableByWindowBackground_(self, flag):
        self.movable = flag
```

`_FakeView`에 메서드 추가:

```python
    def setCompact_(self, flag):
        self.compact = flag

    def setDimmed_(self, flag):
        self.dimmed = flag
```

파일 끝에 테스트 추가:

```python
def test_set_mode_pill_uses_full_pill_and_ignores_mouse():
    overlay = _overlay()
    overlay._mode = "cursor"
    overlay.set_mode("pill", None)
    assert overlay._mode == "pill"
    assert overlay._view.compact is False
    assert overlay._panel.ignores_mouse is True
    assert overlay._panel.movable is False


def test_set_mode_unknown_falls_back_to_pill():
    overlay = _overlay()
    overlay.set_mode("bogus", None)
    assert overlay._mode == "pill"


def test_current_origin_none_when_not_pinned_or_hidden():
    overlay = _overlay(visible=False)
    overlay._mode = "pinned"
    assert overlay.current_origin() is None
```

`_overlay()` 헬퍼는 `overlay._mode`가 없으면 위 테스트에서 직접 설정하므로 그대로 둔다. 단, `set_mode`가 참조하는 속성 초기화를 위해 `_overlay()` 헬퍼의 `return overlay` 직전에 다음 줄을 추가:

```python
    overlay._mode = "pill"
    overlay._pin_xy = None
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/pytest test_hud_overlay.py -q`
Expected: FAIL (AttributeError — `set_mode`/`current_origin` 없음)

- [ ] **Step 3: 구현** — `DictationOverlay.__init__`의 `self._screen_key = None` 줄 다음에 추가:

```python
        self._mode = "pill"
        self._pin_xy = None
```

`DictationOverlay`에 `_screen_box` 메서드 다음(또는 클래스 내 적당한 위치)에 새 메서드들 추가:

```python
    def _screen_boxes_list(self):
        """모든 화면의 visibleFrame을 (ox, oy, sw, sh) 리스트로. 주 모니터가 첫 번째."""
        boxes = []
        for s in (NSScreen.screens() or []):
            f = s.visibleFrame()
            boxes.append((f.origin.x, f.origin.y, f.size.width, f.size.height))
        return boxes

    def _resolve_pin_xy(self, pin_xy):
        boxes = self._screen_boxes_list()
        if pin_xy:
            px, py = pin_xy
        else:
            px, py = None, None
        return clamp_to_visible(px, py, ICON_SIZE, ICON_SIZE, boxes)

    def set_mode(self, mode, pin_xy=None):
        if self._panel is None or self._view is None:
            return
        mode = normalize_hud_mode(mode)
        self._mode = mode
        self._pin_xy = pin_xy
        try:
            if mode == "pill":
                self._view.setCompact_(False)
                self._panel.setIgnoresMouseEvents_(True)
                self._panel.setMovableByWindowBackground_(False)
                self._screen_key = None  # 다음 show에서 하단중앙 재배치 강제
                self._resize_panel(PANEL_WIDTH, PANEL_HEIGHT, BAR_CORNER_RADIUS)
                return
            # 아이콘(컴팩트) 모드 공통
            self._view.setCompact_(True)
            is_pinned = (mode == "pinned")
            self._panel.setIgnoresMouseEvents_(not is_pinned)
            self._panel.setMovableByWindowBackground_(is_pinned)
            self._view.setFrame_(NSMakeRect(0, 0, ICON_SIZE, ICON_SIZE))
            self._view.setCornerRadius_(ICON_SIZE / 2.0)
            if is_pinned:
                x, y = self._resolve_pin_xy(pin_xy)
                self._panel.setFrame_display_(NSMakeRect(x, y, ICON_SIZE, ICON_SIZE), True)
            else:  # cursor
                self._panel.setFrame_display_(NSMakeRect(0, 0, ICON_SIZE, ICON_SIZE), True)
                self.reposition_to_cursor()
        except Exception as exc:
            print(f"hud_overlay: set_mode error: {exc}")

    def reposition_to_cursor(self):
        if self._panel is None or self._mode != "cursor":
            return
        try:
            sw, sh, ox, oy = self._screen_box()
            p = NSEvent.mouseLocation()
            x = p.x + CURSOR_OFFSET_X
            y = p.y - ICON_SIZE - CURSOR_OFFSET_Y
            x = min(max(x, ox), ox + sw - ICON_SIZE)
            y = min(max(y, oy), oy + sh - ICON_SIZE)
            self._panel.setFrameOrigin_(NSMakePoint(x, y))
        except Exception as exc:
            print(f"hud_overlay: reposition_to_cursor error: {exc}")

    def current_origin(self):
        if self._panel is None or self._mode != "pinned" or not self._visible:
            return None
        try:
            f = self._panel.frame()
            return (float(f.origin.x), float(f.origin.y))
        except Exception:
            return None

    def set_processing(self, flag):
        if self._view is None:
            return
        try:
            self._view.setDimmed_(flag)
        except Exception as exc:
            print(f"hud_overlay: set_processing error: {exc}")
```

`show()` 메서드를 아래로 교체(pill만 커서 모니터 추적):

```python
    def show(self):
        if self._panel is None:
            return
        try:
            if self._mode == "pill":
                self._reposition_for_pointer_screen()
            if not self._visible:
                self._panel.orderFrontRegardless()
                self._visible = True
        except Exception as exc:
            print(f"hud_overlay: show error: {exc}")
```

- [ ] **Step 4: 통과 확인**

Run: `./venv/bin/pytest test_hud_overlay.py -q`
Expected: PASS

- [ ] **Step 5: 문법 검증**

Run: `./venv/bin/python -m py_compile hud_overlay.py`
Expected: 출력 없음

- [ ] **Step 6: 커밋**

```bash
git add hud_overlay.py test_hud_overlay.py
git commit -m "feat: hud mode switching, cursor follow, pin position read"
```

---

## Task 5: 앱 본체 연결 (whisper-dictation)

**Files:**
- Modify: `whisper-dictation.py:724-740` (`_tick_overlay`), `:742-753` (`current_config`), `:782-797` (`_apply_saved_config`)

AppKit/rumps 통합이라 `py_compile` + 전체 pytest 회귀 + 육안 확인.

- [ ] **Step 1: `current_config`에 키 추가** — `current_config`의 `"domain_context": getattr(self, "domain_context", ""),` 줄 다음에 추가:

```python
            "hud_mode": getattr(self, "hud_mode", "pill"),
            "hud_pin_x": getattr(self, "hud_pin_x", None),
            "hud_pin_y": getattr(self, "hud_pin_y", None),
```

- [ ] **Step 2: `_apply_saved_config`에 키 읽기 추가** — `self.domain_context = str(cfg.get("domain_context", "") or "")` 줄 다음에 추가:

```python
        self.hud_mode = hud_overlay.normalize_hud_mode(cfg.get("hud_mode", "pill"))
        self.hud_pin_x = cfg.get("hud_pin_x")
        self.hud_pin_y = cfg.get("hud_pin_y")
```

- [ ] **Step 3: `_tick_overlay` 교체** — `_tick_overlay` 메서드 전체를 아래로 교체:

```python
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
                if mode == "cursor":
                    ov.reposition_to_cursor()
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
```

- [ ] **Step 4: 문법 검증**

Run: `./venv/bin/python -m py_compile whisper-dictation.py`
Expected: 출력 없음

- [ ] **Step 5: 전체 테스트 회귀**

Run: `./venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add whisper-dictation.py
git commit -m "feat: drive hud modes from app tick (apply, cursor follow, pin save)"
```

---

## Task 6: 대시보드 API (dashboard)

**Files:**
- Modify: `dashboard.py:57-69` (GET), `:82-102` (POST apply)
- Test: `test_dashboard_paths.py`

- [ ] **Step 1: 실패 테스트 작성** — `test_dashboard_paths.py` 파일 끝에 추가:

```python
def test_dashboard_config_hud_mode_roundtrip(monkeypatch):
    from types import SimpleNamespace
    fake = SimpleNamespace(
        current_language="ko", languages=["ko", "en", "auto"],
        max_time=300, input_device="", hold_key="cmd_r", toggle_key="alt_r",
        min_volume=35, edit_interrupt_mode="continue", hold_send_enter=True,
        domain_context="", hud_mode="pill", hud_pin_x=None, hud_pin_y=None,
    )
    fake.sync_menu_state = lambda: None
    fake.save_settings = lambda: None
    monkeypatch.setattr(dashboard, "app_instance", fake)

    client = dashboard.flask_app.test_client()
    resp = client.post("/api/config", json={"hud_mode": "pinned"})
    assert resp.status_code == 200
    assert fake.hud_mode == "pinned"
    assert client.get("/api/config").get_json()["hud_mode"] == "pinned"


def test_dashboard_config_hud_mode_rejects_unknown(monkeypatch):
    from types import SimpleNamespace
    fake = SimpleNamespace(
        current_language="ko", languages=["ko"], max_time=300, input_device="",
        hold_key="cmd_r", toggle_key="alt_r", min_volume=35,
        edit_interrupt_mode="continue", hold_send_enter=True, domain_context="",
        hud_mode="pill", hud_pin_x=None, hud_pin_y=None,
    )
    fake.sync_menu_state = lambda: None
    fake.save_settings = lambda: None
    monkeypatch.setattr(dashboard, "app_instance", fake)

    client = dashboard.flask_app.test_client()
    client.post("/api/config", json={"hud_mode": "bogus"})
    assert fake.hud_mode == "pill"
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/pytest test_dashboard_paths.py -q`
Expected: FAIL (KeyError 'hud_mode' in GET 응답)

- [ ] **Step 3: GET 구현** — `get_config()`의 반환 dict에서 `"domain_context": getattr(app_instance, 'domain_context', ''),` 줄 다음에 추가:

```python
        "hud_mode": getattr(app_instance, 'hud_mode', 'pill'),
        "hud_pin_x": getattr(app_instance, 'hud_pin_x', None),
        "hud_pin_y": getattr(app_instance, 'hud_pin_y', None),
```

- [ ] **Step 4: POST 구현** — `post_config`의 `apply()` 안, `if 'edit_interrupt_mode' in data:` 블록 앞에 추가:

```python
        if 'hud_mode' in data:
            m = str(data['hud_mode'])
            app_instance.hud_mode = m if m in ("pill", "pinned", "cursor") else "pill"
```

- [ ] **Step 5: 통과 확인**

Run: `./venv/bin/pytest test_dashboard_paths.py -q`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add dashboard.py test_dashboard_paths.py
git commit -m "feat: dashboard config api for hud_mode"
```

---

## Task 7: 대시보드 UI (templates/dashboard.html)

**Files:**
- Modify: `templates/dashboard.html` (음성 인식 패널 마크업, `fetchConfig`, `updateConfig`)

문자열 치환 작업이라 `pytest`(대시보드 라우트 200) + 육안 확인.

- [ ] **Step 1: 셀렉트 추가** — 음성 인식 패널에서 마이크 셀렉트 바로 다음에 HUD 셀렉트를 넣는다. `<select id="input-device" onchange="updateConfig()"></select>` 문자열을 찾아 그 뒤에 아래를 이어 붙인다:

```html
<label for="hud-mode">받아쓰기 표시</label><select id="hud-mode" onchange="updateConfig()"><option value="pill">알약 — 하단 중앙에 글자와 함께(기본)</option><option value="pinned">아이콘 고정 — 드래그해 둔 자리에 작은 아이콘</option><option value="cursor">아이콘 + 커서 따라가기 — 마우스 옆에 작은 아이콘</option></select><p class="hint">아이콘 모드는 글자 없이 작은 음성 표시만 뜹니다. 고정은 끌어다 둔 자리에 머무르고, 커서 따라가기는 마우스를 따라 움직입니다.</p>
```

- [ ] **Step 2: fetchConfig 반영** — `fetchConfig` 함수의 `document.getElementById("domain-context").value=d.domain_context||"";` 바로 다음(같은 줄 안)에 삽입:

```javascript
document.getElementById("hud-mode").value=d.hud_mode||"pill";
```

- [ ] **Step 3: updateConfig 전송** — `updateConfig` 함수의 POST body 객체에서 `domain_context:document.getElementById("domain-context").value` 다음에 추가:

```javascript
,hud_mode:document.getElementById("hud-mode").value
```

(즉 `...domain_context:document.getElementById("domain-context").value,hud_mode:document.getElementById("hud-mode").value})` 형태가 되도록.)

- [ ] **Step 4: 라우트 검증**

Run: `./venv/bin/pytest test_dashboard_paths.py -q`
Expected: PASS (`/` 및 자산 라우트 정상)

- [ ] **Step 5: 육안 확인용 메모** — 실행 후 `http://127.0.0.1:5001`에서 "음성 인식" 칸에 "받아쓰기 표시" 셀렉트가 보이고, 값 변경 시 저장되는지 확인(이 단계는 e2e에서).

- [ ] **Step 6: 커밋**

```bash
git add templates/dashboard.html
git commit -m "feat: dashboard hud mode selector"
```

---

## Task 8: 정리 + 전체 검증

**Files:**
- Create/Modify: `.gitignore`

- [ ] **Step 1: .superpowers 무시** — `.gitignore`에 `.superpowers/`가 없으면 한 줄 추가.

Run: `grep -q '^\.superpowers/' .gitignore || printf '\n.superpowers/\n' >> .gitignore`

- [ ] **Step 2: 전체 컴파일 검증**

Run: `./venv/bin/python -m py_compile whisper-dictation.py dashboard.py dictation_history.py hud_overlay.py`
Expected: 출력 없음

- [ ] **Step 3: 전체 테스트**

Run: `./venv/bin/pytest -q`
Expected: PASS (모든 테스트)

- [ ] **Step 4: 커밋**

```bash
git add .gitignore
git commit -m "chore: ignore .superpowers brainstorm artifacts"
```

- [ ] **Step 5: e2e 육안 확인(사용자와 함께)** — `./run.sh`로 앱 실행 후:
  - 대시보드에서 "알약" 선택 → 받아쓰기 시 하단 중앙 알약, 커서를 다른 모니터로 옮기면 따라옴.
  - "아이콘 고정" 선택 → 작은 원형 아이콘, 드래그해 다른 자리로 이동, 앱 재시작 후에도 그 자리 유지, 커서를 다른 모니터로 옮겨도 안 따라감.
  - "커서 따라가기" 선택 → 아이콘이 마우스 옆에 붙어 모니터 넘나들며 따라옴.
  - 각 모드에서 변환 중 아이콘이 살짝 흐려지는지 확인.

---

## Self-Review (작성자 점검 결과)

- 스펙 커버리지: A/B/C 모드(Task 3·4·5), 멀티모니터 동작(show 분기·reposition·clamp), 36px 아이콘(ICON_SIZE), 변환 중 흐림(set_processing/dimmed), 설정 저장·노출(Task 1·6·7), 드래그 저장(current_origin + tick 폴링) 모두 태스크에 매핑됨.
- 플레이스홀더: 없음(모든 코드 단계에 실제 코드 포함).
- 타입/이름 일관성: `set_mode`/`reposition_to_cursor`/`current_origin`/`set_processing`/`setCompact_`/`setDimmed_`/`normalize_hud_mode`/`clamp_to_visible` 명칭이 정의-사용 간 일치. config 키 `hud_mode`/`hud_pin_x`/`hud_pin_y` 일관.
