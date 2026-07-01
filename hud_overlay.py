# hud_overlay.py
"""In-process native (PyObjC/AppKit) floating overlay for the dictation app.

Replaces the old subprocess-based tkinter HUD so the mic level meter works
INSIDE the packaged .app (where sys.executable is the app binary, not python).

CRITICAL THREADING CONTRACT:
- All AppKit objects here MUST be created and mutated on the MAIN thread only.
- The window is built lazily inside get_overlay(), which is only ever called
  from StatusBarApp._tick_overlay (a rumps.Timer callback running on the main
  thread). Importing this module does NOT build any window.
- We never call NSApplication.run(); rumps owns the run loop.

ROBUSTNESS:
- Any AppKit failure prints a warning and degrades gracefully. Recording must
  keep working even if the overlay cannot draw.

LAYOUT:
- Floats near the BOTTOM-center of the pointer screen, low enough to avoid prompt text.
- A slim macOS-style status pill shows a tiny reactive voice meter and state text.
"""

PANEL_WIDTH = 104.0
PANEL_HEIGHT = 44.0
BOTTOM_OFFSET = 24.0
BAR_CORNER_RADIUS = PANEL_HEIGHT / 2.0
HUD_BG_RGBA = (90, 86, 88, 0.62)
HUD_TEXT_RGBA = (255, 250, 248, 0.96)
HUD_BAR_RGBA = (255, 111, 133, 0.96)
HUD_HAS_SHADOW = False

# 라벨(상태 글자) 배치. 측정·그리기·알약 폭 계산이 같은 값을 공유해야 긴 글자가 잘리지
# 않는다("모델 불러오는 중…" 처럼 기본 폭을 넘는 라벨은 알약을 늘려서 보여준다).
PILL_SIDE_PAD = 14.0
METER_BAR_WIDTH = 4.0
METER_BAR_GAP = 3.0
METER_WIDTH = (METER_BAR_WIDTH * 3.0) + (METER_BAR_GAP * 2.0)
METER_LABEL_GAP = 9.0
PILL_CONTENT_OPTICAL_OFFSET_X = 0.0
LABEL_FONT_SIZE = 13.0
LABEL_FONT_WEIGHT = 0.42


def jelly_bar_heights(level):
    """Clamp microphone level and return symmetric (left, center, right) bar heights.

    Resting bars are deliberately short so the difference between silence and
    speech is obvious: at level 0 they sit near-flat, and they grow several-fold
    as the microphone picks up the voice.
    """
    level = min(1.0, max(0.0, float(level)))
    visual_level = level ** 0.5
    side = 8.0 + (6.0 * visual_level)
    center = 14.0 + (8.0 * visual_level)
    return side, center, side


def voice_bar_corner_radius(width, height):
    """Match the app icon voice bars: rounded ends are based on bar width."""
    return min(float(width), float(height)) / 2.0


# 표시 모드와 아이콘(컴팩트) 사양. AppKit 없이도 import/테스트되도록 모듈 상단에 둔다.
HUD_MODES = ("pill", "pinned")
ICON_SIZE = 24.0
ICON_BAR_WIDTH = 3.5
ICON_BAR_GAP = 2.5
PIN_DEFAULT_MARGIN = 24.0


def normalize_hud_mode(value):
    """알 수 없는 값(옛 'caret'/'cursor' 포함)은 안전하게 'pill'로 떨어뜨린다."""
    return value if value in HUD_MODES else "pill"


def pill_layout_for_label(pill_width, text_width):
    """Return (meter_x, label_x) with a slight left optical correction.

    The text label has much more visual weight than the three thin meter bars, so
    a purely geometric center reads a little right-heavy in the live HUD.
    """
    content_width = METER_WIDTH + METER_LABEL_GAP + max(0.0, float(text_width))
    centered_left = (float(pill_width) - content_width) / 2.0
    left = max(PILL_SIDE_PAD, centered_left + PILL_CONTENT_OPTICAL_OFFSET_X)
    return left, left + METER_WIDTH + METER_LABEL_GAP


def pill_width_for_label(text_width):
    """라벨의 픽셀 폭을 받아 알약 전체 폭을 돌려준다. 짧은 라벨('듣는 중')은 기본 폭을
    유지하고, 긴 라벨('모델 불러오는 중…')은 글자가 다 보이도록 늘린다."""
    needed = (PILL_SIDE_PAD * 2.0) + METER_WIDTH + METER_LABEL_GAP + max(0.0, float(text_width))
    return max(PANEL_WIDTH, needed)


def label_origin_y(pill_height, text_height):
    """Return the label origin that centers AppKit's measured text box."""
    return (float(pill_height) - float(text_height)) / 2.0


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


# Importing AppKit at module load is safe (no window is built). Guard anyway so
# an import failure never kills the host app.
try:
    import objc
    from AppKit import (
        NSColor,
        NSPanel,
        NSView,
        NSBezierPath,
        NSFont,
        NSEvent,
        NSScreen,
        NSMakeRect,
        NSMakePoint,
        NSForegroundColorAttributeName,
        NSFontAttributeName,
        NSWindowStyleMaskBorderless,
        NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSStatusWindowLevel,
    )
    from Foundation import NSString
    _APPKIT_OK = True
except Exception as _exc:  # pragma: no cover - depends on runtime env
    print(f"hud_overlay: AppKit import failed, overlay disabled: {_exc}")
    _APPKIT_OK = False


if _APPKIT_OK:

    def _rgb(r, g, b, a=1.0):
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(
            r / 255.0, g / 255.0, b / 255.0, a
        )

    def _label_attrs():
        """상태 글자의 색·글꼴. 그리기와 폭 측정이 같은 속성을 써야 측정 오차가 없다."""
        return {
            NSForegroundColorAttributeName: _rgb(*HUD_TEXT_RGBA),
            NSFontAttributeName: NSFont.systemFontOfSize_weight_(
                LABEL_FONT_SIZE, LABEL_FONT_WEIGHT
            ),
        }

    class _OverlayView(NSView):
        """Custom view that draws level-reactive jelly bars."""

        def initWithFrame_(self, frame):
            self = objc.super(_OverlayView, self).initWithFrame_(frame)
            if self is None:
                return None
            self._level = 0.0
            self._elapsed = 0
            self._blink_on = True
            self._label_text = "듣는 중"
            self._corner_radius = BAR_CORNER_RADIUS
            self._compact = False
            self._dimmed = False
            return self

        def setCornerRadius_(self, r):
            self._corner_radius = r
            self.setNeedsDisplay_(True)

        def _draw_background(self):
            b = self.bounds()
            w, h = b.size.width, b.size.height
            r = min(self._corner_radius, w / 2.0, h / 2.0)
            rect = NSMakeRect(0.0, 0.0, w, h)
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, r, r)
            _rgb(*HUD_BG_RGBA).setFill()
            path.fill()

        def setValues_(self, values):
            # values = (level, elapsed_seconds, blink_on)
            # Smooth abrupt microphone changes so the meter breathes instead of
            # jittering, but lean toward the new sample so it visibly reacts.
            self._level = (self._level * 0.25) + (float(values[0]) * 0.75)
            self._elapsed = values[1]
            self._blink_on = values[2]
            self.setNeedsDisplay_(True)

        def setLabelText_(self, text):
            self._label_text = text
            self.setNeedsDisplay_(True)

        def setCompact_(self, flag):
            self._compact = bool(flag)
            self.setNeedsDisplay_(True)

        def setDimmed_(self, flag):
            self._dimmed = bool(flag)
            self.setNeedsDisplay_(True)

        def drawRect_(self, rect):
            try:
                self._draw()
            except Exception as exc:
                print(f"hud_overlay: drawRect error: {exc}")

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

            text_width = float(NSString.stringWithString_(self._label_text or "듣는 중").sizeWithAttributes_(_label_attrs()).width)
            start_x, _label_x = pill_layout_for_label(bounds.size.width, text_width)
            bar_w = METER_BAR_WIDTH
            gap = METER_BAR_GAP

            for index, height in enumerate(heights):
                x = start_x + (index * (bar_w + gap))
                y = cy - (height / 2.0)
                self._draw_jelly_rect(x, y, bar_w, height)
            self._draw_label(_label_x)

        def _draw_label(self, x):
            text = self._label_text or "듣는 중"
            label = NSString.stringWithString_(text)
            attrs = _label_attrs()
            y = label_origin_y(self.bounds().size.height, label.sizeWithAttributes_(attrs).height)
            # Plain Python str does not expose the AppKit drawing category; wrap
            # it in an NSString so drawAtPoint_withAttributes_ is available.
            label.drawAtPoint_withAttributes_(NSMakePoint(x, y), attrs)

        def _draw_jelly_rect(self, x, y, width, height, alpha=0.94):
            _rgb(HUD_BAR_RGBA[0], HUD_BAR_RGBA[1], HUD_BAR_RGBA[2], alpha).setFill()
            radius = voice_bar_corner_radius(width, height)
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, y, width, height), radius, radius
            ).fill()


class DictationOverlay:
    """Singleton-style wrapper around the NSPanel overlay. Main thread only."""

    def __init__(self):
        self._panel = None
        self._view = None
        self._blink_on = True
        self._visible = False
        self._screen_key = None
        self._mode = "pill"
        self._pin_xy = None
        if not _APPKIT_OK:
            return
        try:
            self._build()
        except Exception as exc:
            print(f"hud_overlay: failed to build overlay: {exc}")
            self._panel = None
            self._view = None

    def _screen_box(self):
        # visibleFrame excludes the Dock and menu bar. Use the
        # screen containing the pointer: the user normally clicks the text field
        # before dictating, so this follows the monitor where typing is happening.
        screens = list(NSScreen.screens() or [])
        pointer = NSEvent.mouseLocation()
        screen = next((s for s in screens if self._contains_point(s.frame(), pointer)), None)
        if screen is None:
            screen = NSScreen.mainScreen()
        if screen is not None:
            f = screen.visibleFrame()
            return f.size.width, f.size.height, f.origin.x, f.origin.y
        return 1440.0, 860.0, 0.0, 0.0

    @staticmethod
    def _contains_point(frame, point):
        return (
            frame.origin.x <= point.x < frame.origin.x + frame.size.width
            and frame.origin.y <= point.y < frame.origin.y + frame.size.height
        )

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
            # 아이콘 고정 모드: 드래그로 옮길 수 있는 작은 원형 아이콘
            self._view.setCompact_(True)
            self._panel.setIgnoresMouseEvents_(False)
            self._panel.setMovableByWindowBackground_(True)
            self._view.setFrame_(NSMakeRect(0, 0, ICON_SIZE, ICON_SIZE))
            self._view.setCornerRadius_(ICON_SIZE / 2.0)
            x, y = self._resolve_pin_xy(pin_xy)
            self._panel.setFrame_display_(NSMakeRect(x, y, ICON_SIZE, ICON_SIZE), True)
        except Exception as exc:
            print(f"hud_overlay: set_mode error: {exc}")

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

    def _current_screen_key(self):
        sw, sh, ox, oy = self._screen_box()
        return sw, sh, ox, oy

    def _reposition_for_pointer_screen(self):
        if self._panel is None:
            return
        screen_key = self._current_screen_key()
        if screen_key == self._screen_key:
            return
        frame = self._panel.frame()
        self._screen_key = screen_key
        self._resize_panel(frame.size.width, frame.size.height, self._view._corner_radius)

    def _build(self):
        sw, sh, ox, oy = self._screen_box()
        self._screen_key = (sw, sh, ox, oy)
        x = ox + (sw - PANEL_WIDTH) / 2.0
        # AppKit y origin is bottom-left; sit just above the Dock.
        y = oy + BOTTOM_OFFSET

        rect = NSMakeRect(x, y, PANEL_WIDTH, PANEL_HEIGHT)
        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style_mask, NSBackingStoreBuffered, False
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setOpaque_(False)
        # Transparent window; the rounded shape is drawn by the layer-backed view.
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(HUD_HAS_SHADOW)
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setFloatingPanel_(True)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        view = _OverlayView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT)
        )
        view.setCornerRadius_(BAR_CORNER_RADIUS)
        panel.setContentView_(view)

        self._panel = panel
        self._view = view

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

    def show_status(self, label):
        if self._view is None:
            return
        try:
            self._view.setLabelText_(label)
            if self._mode == "pill":
                self._fit_pill_to_label(label)
            self.show()
        except Exception as exc:
            print(f"hud_overlay: show_status error: {exc}")

    def _measure_label_width(self, text):
        """라벨을 그릴 글꼴로 잰 픽셀 폭. 그리기와 항상 같은 _label_attrs 를 쓴다."""
        s = NSString.stringWithString_(text or "")
        return float(s.sizeWithAttributes_(_label_attrs()).width)

    def _fit_pill_to_label(self, label):
        """알약 폭을 라벨이 다 보이도록 맞춘다(폭이 실제로 달라질 때만 리사이즈해 매 틱
        흔들림을 막는다). 아이콘 고정 모드는 라벨을 안 그리므로 pill 모드 전용이다."""
        if self._panel is None:
            return
        target = pill_width_for_label(self._measure_label_width(label))
        current = float(self._panel.frame().size.width)
        if abs(target - current) < 1.0:
            return
        self._resize_panel(target, PANEL_HEIGHT, BAR_CORNER_RADIUS)

    def _resize_panel(self, width, height, radius):
        sw, sh, ox, oy = self._screen_box()
        self._screen_key = (sw, sh, ox, oy)
        x = ox + (sw - width) / 2.0
        y = oy + BOTTOM_OFFSET
        self._panel.setFrame_display_(NSMakeRect(x, y, width, height), True)
        self._view.setFrame_(NSMakeRect(0, 0, width, height))
        self._view.setCornerRadius_(radius)

    def hide(self):
        if self._panel is None:
            return
        try:
            if not self._visible:
                return
            if self._visible:
                self._panel.orderOut_(None)
                self._visible = False
        except Exception as exc:
            print(f"hud_overlay: hide error: {exc}")

    def update(self, level, elapsed_seconds):
        if self._view is None:
            return
        try:
            self._blink_on = not self._blink_on
            self._view.setValues_((float(level), int(elapsed_seconds), self._blink_on))
        except Exception as exc:
            print(f"hud_overlay: update error: {exc}")


_OVERLAY = None


def get_overlay():
    """Lazy singleton. Build the window on first (main-thread) call."""
    global _OVERLAY
    if _OVERLAY is None:
        _OVERLAY = DictationOverlay()
    return _OVERLAY
