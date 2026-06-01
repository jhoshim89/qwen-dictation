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
"""

PANEL_WIDTH = 300.0
PANEL_HEIGHT = 46.0
TOP_OFFSET = 50.0  # pixels down from the top of the main screen
REVIEW_WIDTH = 460.0
REVIEW_MIN_HEIGHT = 120.0


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
        NSScreen,
        NSMakeRect,
        NSMakePoint,
        NSWindowStyleMaskBorderless,
        NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSStatusWindowLevel,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
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

    class _OverlayView(NSView):
        """Custom view that draws the dot, label, level meter and elapsed time."""

        def initWithFrame_(self, frame):
            self = objc.super(_OverlayView, self).initWithFrame_(frame)
            if self is None:
                return None
            self._level = 0.0
            self._elapsed = 0
            self._blink_on = True
            self._label_text = "로컬 받아쓰기 중"
            self._review_text = None  # None 이면 막대 모드, 문자열이면 리뷰 모드
            return self

        def setValues_(self, values):
            # values = (level, elapsed_seconds, blink_on)
            self._level = values[0]
            self._elapsed = values[1]
            self._blink_on = values[2]
            self.setNeedsDisplay_(True)

        def setReviewText_(self, text):
            self._review_text = text
            self.setNeedsDisplay_(True)

        def setLabelText_(self, text):
            self._label_text = text
            self.setNeedsDisplay_(True)

        def drawRect_(self, rect):
            try:
                self._draw()
            except Exception as exc:
                print(f"hud_overlay: drawRect error: {exc}")

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
            hint = "⌘ 다시·Enter: 보내기   Tab: 수정   Esc: 취소"
            hint_attrs = {
                NSFontAttributeName: NSFont.boldSystemFontOfSize_(11.0),
                NSForegroundColorAttributeName: _rgb(165, 180, 252, 1.0),
            }
            hint_str = NSString.stringWithString_(hint)
            hint_str.drawAtPoint_withAttributes_(NSMakePoint(14.0, 10.0), hint_attrs)

        def _draw(self):
            if self._review_text is not None:
                self._draw_review()
                return
            bounds = self.bounds()
            h = bounds.size.height

            # Layout coordinates (origin bottom-left in AppKit).
            dot_cx = 18.0
            dot_cy = h / 2.0
            dot_r = 5.0

            # Blinking red dot.
            dot_alpha = 1.0 if self._blink_on else 0.25
            _rgb(239, 68, 68, dot_alpha).setFill()
            dot_rect = NSMakeRect(dot_cx - dot_r, dot_cy - dot_r, dot_r * 2, dot_r * 2)
            NSBezierPath.bezierPathWithOvalInRect_(dot_rect).fill()

            # Label text for recording or transcription progress.
            label = self._label_text
            label_font = NSFont.boldSystemFontOfSize_(12.0)
            label_attrs = {
                NSFontAttributeName: label_font,
                NSForegroundColorAttributeName: _rgb(243, 244, 246, 1.0),
            }
            label_str = NSString.stringWithString_(label)
            label_size = label_str.sizeWithAttributes_(label_attrs)
            label_x = 32.0
            label_y = (h - label_size.height) / 2.0
            label_str.drawAtPoint_withAttributes_(
                NSMakePoint(label_x, label_y), label_attrs
            )

            # Elapsed time "MM:SS" on the right.
            mins, secs = divmod(int(self._elapsed), 60)
            time_text = f"{mins:02d}:{secs:02d}"
            time_font = NSFont.boldSystemFontOfSize_(12.0)
            time_attrs = {
                NSFontAttributeName: time_font,
                NSForegroundColorAttributeName: _rgb(165, 180, 252, 1.0),
            }
            time_str = NSString.stringWithString_(time_text)
            time_size = time_str.sizeWithAttributes_(time_attrs)
            time_x = bounds.size.width - time_size.width - 14.0
            time_y = (h - time_size.height) / 2.0
            time_str.drawAtPoint_withAttributes_(
                NSMakePoint(time_x, time_y), time_attrs
            )

            # Level meter track between the label and the time.
            track_x = label_x + label_size.width + 10.0
            track_right = time_x - 10.0
            track_w = track_right - track_x
            track_h = 8.0
            track_y = (h - track_h) / 2.0
            if track_w < 10.0:
                return  # not enough room; skip the meter

            radius = track_h / 2.0
            track_rect = NSMakeRect(track_x, track_y, track_w, track_h)
            _rgb(30, 41, 59, 1.0).setFill()  # dark gray track
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                track_rect, radius, radius
            ).fill()

            level = self._level
            if level < 0.0:
                level = 0.0
            elif level > 1.0:
                level = 1.0
            fill_w = track_w * level
            if fill_w > 0.0:
                if level < 0.5:
                    fill_color = _rgb(34, 197, 94)   # #22c55e green
                elif level < 0.8:
                    fill_color = _rgb(234, 179, 8)   # #eab308 yellow
                else:
                    fill_color = _rgb(239, 68, 68)   # #ef4444 red
                fill_rect = NSMakeRect(track_x, track_y, fill_w, track_h)
                fill_color.setFill()
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    fill_rect, radius, radius
                ).fill()


class DictationOverlay:
    """Singleton-style wrapper around the NSPanel overlay. Main thread only."""

    def __init__(self):
        self._panel = None
        self._view = None
        self._blink_on = True
        self._visible = False
        self._review_mode = False
        if not _APPKIT_OK:
            return
        try:
            self._build()
        except Exception as exc:
            print(f"hud_overlay: failed to build overlay: {exc}")
            self._panel = None
            self._view = None

    def _build(self):
        screen = NSScreen.mainScreen()
        if screen is not None:
            frame = screen.frame()
            screen_w = frame.size.width
            screen_h = frame.size.height
            screen_origin_x = frame.origin.x
            screen_origin_y = frame.origin.y
        else:
            screen_w, screen_h = 1440.0, 900.0
            screen_origin_x = screen_origin_y = 0.0

        x = screen_origin_x + (screen_w - PANEL_WIDTH) / 2.0
        # AppKit y origin is bottom-left; position TOP_OFFSET down from the top.
        y = screen_origin_y + screen_h - PANEL_HEIGHT - TOP_OFFSET

        rect = NSMakeRect(x, y, PANEL_WIDTH, PANEL_HEIGHT)
        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style_mask, NSBackingStoreBuffered, False
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.82)
        )
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
        panel.setContentView_(view)

        self._panel = panel
        self._view = view

    def show(self):
        if self._panel is None:
            return
        try:
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

    def show_review(self, text):
        """리뷰 패널을 화면 위쪽에 띄운다(아래로 커지며 받아쓴 글 표시)."""
        if self._panel is None or self._view is None:
            return
        try:
            self._resize_panel(REVIEW_WIDTH, REVIEW_MIN_HEIGHT)
            self._view.setReviewText_(text)
            self._panel.orderFrontRegardless()
            self._visible = True
            self._review_mode = True
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

    def hide(self):
        if self._panel is None:
            return
        try:
            if not self._visible and not self._review_mode:
                return
            if self._view is not None:
                self._view.setReviewText_(None)
            if self._review_mode:
                self._resize_panel(PANEL_WIDTH, PANEL_HEIGHT)
                self._review_mode = False
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
