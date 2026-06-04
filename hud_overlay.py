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
- Floats near the BOTTOM-center of the pointer screen, lifted above prompt inputs.
- A slim macOS-style status pill shows a tiny reactive voice meter and state text.
"""

PANEL_WIDTH = 92.0
PANEL_HEIGHT = 40.0
BOTTOM_OFFSET = 86.0
BAR_CORNER_RADIUS = PANEL_HEIGHT / 2.0


def jelly_bar_heights(level):
    """Clamp microphone level and return symmetric (left, center, right) bar heights.

    Resting bars are deliberately short so the difference between silence and
    speech is obvious: at level 0 they sit near-flat, and they grow several-fold
    as the microphone picks up the voice.
    """
    level = min(1.0, max(0.0, float(level)))
    side = 5.0 + (8.0 * level)
    center = 8.0 + (16.0 * level)
    return side, center, side


# 표시 모드와 아이콘(컴팩트) 사양. AppKit 없이도 import/테스트되도록 모듈 상단에 둔다.
# "caret" = 글자가 입력되는 텍스트 커서 위치를 따라간다(마우스 커서 아님).
HUD_MODES = ("pill", "pinned", "caret")
ICON_SIZE = 36.0
ICON_BAR_WIDTH = 3.5
ICON_BAR_GAP = 2.5
PIN_DEFAULT_MARGIN = 24.0
CARET_GAP = 8.0  # 텍스트 커서 오른쪽으로 이만큼 띄워 아이콘을 둔다


def normalize_hud_mode(value):
    """알 수 없는 값은 안전하게 'pill'로 떨어뜨린다. 옛 값 'cursor'는 'caret'로 옮긴다."""
    if value == "cursor":
        return "caret"
    return value if value in HUD_MODES else "pill"


def caret_icon_origin(caret_rect_topleft, main_screen_height, icon_size, gap=CARET_GAP):
    """텍스트 커서(caret)의 화면 사각형을 받아 아이콘을 둘 AppKit 좌표(좌하단 원점)를 돌려준다.

    caret_rect_topleft = (x, y, w, h). AX가 주는 좌표는 주 모니터 좌상단 원점이라
    y를 뒤집어 Cocoa(좌하단 원점)로 바꾼다. 아이콘은 커서 오른쪽, 세로 중앙에 둔다."""
    cx, cy, cw, ch = caret_rect_topleft
    appkit_y = main_screen_height - cy - ch
    x = cx + cw + gap
    y = appkit_y + (ch - icon_size) / 2.0
    return float(x), float(y)


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


# 텍스트 커서(caret) 위치 추적용 접근성 API. 별도 guard: 실패해도 오버레이는 살아있고
# caret 모드만 폴백한다. 이 프로세스가 손쉬운 사용 권한이 있어야 실제 좌표가 나온다.
try:
    from ApplicationServices import (
        AXUIElementCreateSystemWide,
        AXUIElementCopyAttributeValue,
        AXUIElementCopyParameterizedAttributeValue,
        AXValueGetValue,
        kAXFocusedUIElementAttribute,
        kAXSelectedTextRangeAttribute,
        kAXBoundsForRangeParameterizedAttribute,
        kAXValueCGRectType,
    )
    _AX_OK = True
except Exception as _ax_exc:  # pragma: no cover - depends on runtime env
    print(f"hud_overlay: Accessibility import failed, caret follow disabled: {_ax_exc}")
    _AX_OK = False


if _APPKIT_OK:

    def _rgb(r, g, b, a=1.0):
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(
            r / 255.0, g / 255.0, b / 255.0, a
        )

    # Quiet Dictation palette: darker and slimmer so it reads as a system HUD,
    # not as a decorative badge over the user's writing surface.
    BG_RGBA = (34, 31, 32, 0.58)
    BORDER_RGBA = (255, 255, 255, 0.11)
    TEXT_RGBA = (255, 250, 248, 0.94)
    JELLY_RGBA = (255, 111, 133, 0.86)
    JELLY_HALO_RGBA = (255, 111, 133, 0.13)
    JELLY_HIGHLIGHT_RGBA = (255, 190, 201, 0.64)
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
            rect = NSMakeRect(0.5, 0.5, w - 1.0, h - 1.0)
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, r, r)
            _rgb(*BG_RGBA).setFill()
            path.fill()
            path.setLineWidth_(1.0)
            _rgb(*BORDER_RGBA).setStroke()
            path.stroke()

        def setValues_(self, values):
            # values = (level, elapsed_seconds, blink_on)
            # Smooth abrupt microphone changes so the orb breathes instead of
            # jittering, but lean toward the new sample so it visibly reacts.
            self._level = (self._level * 0.4) + (float(values[0]) * 0.6)
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

            bar_w = 4.0
            gap = 4.0
            start_x = 14.0

            for index, height in enumerate(heights):
                x = start_x + (index * (bar_w + gap))
                y = cy - (height / 2.0)
                self._draw_jelly_rect(x, y, bar_w, height)
            self._draw_label()

        def _draw_label(self):
            text = self._label_text or "듣는 중"
            attrs = {
                NSForegroundColorAttributeName: _rgb(*TEXT_RGBA),
                NSFontAttributeName: NSFont.systemFontOfSize_weight_(13.0, 0.42),
            }
            # Plain Python str does not expose the AppKit drawing category; wrap
            # it in an NSString so drawAtPoint_withAttributes_ is available.
            NSString.stringWithString_(text).drawAtPoint_withAttributes_(
                NSMakePoint(40.0, 11.0), attrs
            )

        def _draw_jelly_rect(self, x, y, width, height, alpha=0.94):
            halo = 2.0
            _rgb(*JELLY_HALO_RGBA).setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x - halo, y - halo, width + (halo * 2.0), height + (halo * 2.0)),
                (min(width, height) + (halo * 2.0)) / 2.0,
                (min(width, height) + (halo * 2.0)) / 2.0,
            ).fill()
            _rgb(JELLY_RGBA[0], JELLY_RGBA[1], JELLY_RGBA[2], alpha).setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, y, width, height), height / 2.0, height / 2.0
            ).fill()
            highlight_width = max(3.0, width - 4.0)
            _rgb(*JELLY_HIGHLIGHT_RGBA).setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x + 0.8, y + height - 3.4, highlight_width, 1.4), 0.7, 0.7
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
        self._last_caret_xy = None
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
            else:  # caret(타이핑되는 텍스트 커서 위치)
                self._panel.setFrame_display_(NSMakeRect(0, 0, ICON_SIZE, ICON_SIZE), True)
                self.reposition_to_caret()
        except Exception as exc:
            print(f"hud_overlay: set_mode error: {exc}")

    def _main_screen_height(self):
        try:
            screens = NSScreen.screens()
            if screens and len(screens):
                return float(screens[0].frame().size.height)
        except Exception:
            pass
        return 900.0

    def _caret_rect_topleft(self):
        """포커스된 입력의 텍스트 커서 화면 사각형(좌상단 원점) (x,y,w,h) 또는 None.
        앱이 caret 위치를 안 내주거나 권한이 없으면 None."""
        if not _AX_OK:
            return None
        try:
            sysw = AXUIElementCreateSystemWide()
            err, focused = AXUIElementCopyAttributeValue(
                sysw, kAXFocusedUIElementAttribute, None)
            if err != 0 or focused is None:
                return None
            err, rng = AXUIElementCopyAttributeValue(
                focused, kAXSelectedTextRangeAttribute, None)
            if err != 0 or rng is None:
                return None
            err, bounds = AXUIElementCopyParameterizedAttributeValue(
                focused, kAXBoundsForRangeParameterizedAttribute, rng, None)
            if err != 0 or bounds is None:
                return None
            ok, rect = AXValueGetValue(bounds, kAXValueCGRectType, None)
            if not ok:
                return None
            return (float(rect.origin.x), float(rect.origin.y),
                    float(rect.size.width), float(rect.size.height))
        except Exception as exc:
            print(f"hud_overlay: caret query error: {exc}")
            return None

    def _clamp_into_some_screen(self, x, y):
        boxes = self._screen_boxes_list()
        cx, cy = x + ICON_SIZE / 2.0, y + ICON_SIZE / 2.0
        target = next(((ox, oy, sw, sh) for ox, oy, sw, sh in boxes
                       if ox <= cx <= ox + sw and oy <= cy <= oy + sh), None)
        if target is None and boxes:
            target = boxes[0]
        if target is None:
            return x, y
        ox, oy, sw, sh = target
        x = min(max(x, ox), ox + sw - ICON_SIZE)
        y = min(max(y, oy), oy + sh - ICON_SIZE)
        return x, y

    def reposition_to_caret(self):
        if self._panel is None or self._mode != "caret":
            return
        try:
            rect = self._caret_rect_topleft()
            if rect is not None:
                x, y = caret_icon_origin(rect, self._main_screen_height(), ICON_SIZE)
                self._last_caret_xy = (x, y)
            elif self._last_caret_xy is not None:
                x, y = self._last_caret_xy
            else:
                # 폴백: caret을 못 찾으면 포인터 화면 하단 중앙(마우스 추적 아님)
                sw, sh, ox, oy = self._screen_box()
                x = ox + (sw - ICON_SIZE) / 2.0
                y = oy + PIN_DEFAULT_MARGIN
            x, y = self._clamp_into_some_screen(x, y)
            self._panel.setFrameOrigin_(NSMakePoint(x, y))
        except Exception as exc:
            print(f"hud_overlay: reposition_to_caret error: {exc}")

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
        panel.setHasShadow_(True)
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
            self.show()
        except Exception as exc:
            print(f"hud_overlay: show_status error: {exc}")

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
