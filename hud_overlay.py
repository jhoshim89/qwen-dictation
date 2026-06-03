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
- Three small raspberry jelly bars gently expand with microphone level while recording.
"""

PANEL_WIDTH = 76.0
PANEL_HEIGHT = 76.0
BOTTOM_OFFSET = 96.0
BAR_CORNER_RADIUS = PANEL_HEIGHT / 2.0


def jelly_bar_heights(level):
    """Clamp microphone level and return symmetric (left, center, right) bar heights."""
    level = min(1.0, max(0.0, float(level)))
    side = 20.0 + (10.0 * level)
    center = 30.0 + (25.0 * level)
    return side, center, side


# Importing AppKit at module load is safe (no window is built). Guard anyway so
# an import failure never kills the host app.
try:
    import objc
    from AppKit import (
        NSColor,
        NSPanel,
        NSView,
        NSBezierPath,
        NSEvent,
        NSScreen,
        NSMakeRect,
        NSWindowStyleMaskBorderless,
        NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSStatusWindowLevel,
    )
    _APPKIT_OK = True
except Exception as _exc:  # pragma: no cover - depends on runtime env
    print(f"hud_overlay: AppKit import failed, overlay disabled: {_exc}")
    _APPKIT_OK = False


if _APPKIT_OK:

    def _rgb(r, g, b, a=1.0):
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(
            r / 255.0, g / 255.0, b / 255.0, a
        )

    # Warm Jelly Voice palette.
    BG_RGBA = (255, 253, 252, 0.96)
    BORDER_RGBA = (234, 221, 216, 0.96)
    JELLY_RGBA = (232, 71, 98, 0.94)
    JELLY_HALO_RGBA = (232, 71, 98, 0.16)
    JELLY_HIGHLIGHT_RGBA = (255, 179, 191, 0.86)
    class _OverlayView(NSView):
        """Custom view that draws level-reactive jelly bars."""

        def initWithFrame_(self, frame):
            self = objc.super(_OverlayView, self).initWithFrame_(frame)
            if self is None:
                return None
            self._level = 0.0
            self._elapsed = 0
            self._blink_on = True
            self._label_text = "로컬 받아쓰기 중"
            self._corner_radius = BAR_CORNER_RADIUS
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
            # Smooth abrupt microphone changes so the orb breathes instead of jittering.
            self._level = (self._level * 0.55) + (float(values[0]) * 0.45)
            self._elapsed = values[1]
            self._blink_on = values[2]
            self.setNeedsDisplay_(True)

        def setLabelText_(self, text):
            self._label_text = text
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
            bar_w = 11.0
            gap = 7.0
            start_x = (bounds.size.width - ((bar_w * 3.0) + (gap * 2.0))) / 2.0

            for index, height in enumerate(heights):
                x = start_x + (index * (bar_w + gap))
                y = cy - (height / 2.0)
                self._draw_jelly_rect(x, y, bar_w, height)

        def _draw_jelly_rect(self, x, y, width, height, alpha=0.94):
            halo = 4.0
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
                NSMakeRect(x + 2.0, y + height - 5.0, highlight_width, 2.5), 1.25, 1.25
            ).fill()


class DictationOverlay:
    """Singleton-style wrapper around the NSPanel overlay. Main thread only."""

    def __init__(self):
        self._panel = None
        self._view = None
        self._blink_on = True
        self._visible = False
        self._screen_key = None
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
