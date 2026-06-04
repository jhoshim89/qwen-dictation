import hud_overlay
from types import SimpleNamespace


class _FakePanel:
    def __init__(self):
        self.hidden = 0
        self.shown = 0
        self.ignores_mouse = None
        self.movable = None

    def orderOut_(self, _):
        self.hidden += 1

    def orderFrontRegardless(self):
        self.shown += 1

    def setIgnoresMouseEvents_(self, flag):
        self.ignores_mouse = flag

    def setMovableByWindowBackground_(self, flag):
        self.movable = flag


class _FakeView:
    def __init__(self):
        self.labels = []
        self.compact = None
        self.dimmed = None

    def setLabelText_(self, text):
        self.labels.append(text)

    def setCompact_(self, flag):
        self.compact = flag

    def setDimmed_(self, flag):
        self.dimmed = flag


def _overlay(visible=False):
    overlay = object.__new__(hud_overlay.DictationOverlay)
    overlay._panel = _FakePanel()
    overlay._view = _FakeView()
    overlay._visible = visible
    overlay._resizes = []
    overlay._resize_panel = lambda width, height, radius: overlay._resizes.append((width, height, radius))
    overlay._reposition_for_pointer_screen = lambda: None
    overlay._mode = "pill"
    overlay._pin_xy = None
    return overlay


def test_hide_idle_overlay_does_not_mutate_window_frame():
    overlay = _overlay()
    overlay.hide()
    assert overlay._resizes == []
    assert overlay._panel.hidden == 0


def test_hide_visible_overlay_orders_window_out():
    overlay = _overlay(visible=True)
    overlay.hide()
    assert overlay._resizes == []
    assert overlay._panel.hidden == 1


def test_show_status_updates_label_without_resizing_panel():
    overlay = _overlay()
    overlay.show_status("받아쓰기 변환 중")
    assert overlay._view.labels == ["받아쓰기 변환 중"]
    assert overlay._resizes == []
    assert overlay._visible is True


def test_contains_point_selects_monitor_bounds():
    frame = SimpleNamespace(
        origin=SimpleNamespace(x=1440, y=0),
        size=SimpleNamespace(width=1920, height=1080),
    )
    assert hud_overlay.DictationOverlay._contains_point(
        frame, SimpleNamespace(x=2000, y=500)
    ) is True
    assert hud_overlay.DictationOverlay._contains_point(
        frame, SimpleNamespace(x=1200, y=500)
    ) is False


def test_recording_overlay_is_lifted_bottom_center_status_pill():
    assert hud_overlay.PANEL_WIDTH == 92.0
    assert hud_overlay.PANEL_HEIGHT == 40.0
    assert hud_overlay.BOTTOM_OFFSET == 86.0


def test_jelly_bar_heights_expand_with_level_clamp_and_stay_symmetric():
    # Resting bars are short; speaking grows them several-fold so the meter
    # visibly reacts to the voice.
    assert hud_overlay.jelly_bar_heights(-1.0) == (5.0, 8.0, 5.0)
    assert hud_overlay.jelly_bar_heights(0.5) == (9.0, 16.0, 9.0)
    assert hud_overlay.jelly_bar_heights(2.0) == (13.0, 24.0, 13.0)


def test_normalize_hud_mode_accepts_known_and_falls_back():
    assert hud_overlay.normalize_hud_mode("pill") == "pill"
    assert hud_overlay.normalize_hud_mode("pinned") == "pinned"
    assert hud_overlay.normalize_hud_mode("caret") == "caret"
    # 옛 값 'cursor'는 'caret'로 옮긴다(마우스 추적 → 타이핑 위치 추적).
    assert hud_overlay.normalize_hud_mode("cursor") == "caret"
    assert hud_overlay.normalize_hud_mode("bogus") == "pill"
    assert hud_overlay.normalize_hud_mode(None) == "pill"


def test_caret_icon_origin_flips_y_and_places_right_of_caret():
    # 주 모니터 높이 900, caret 사각형(좌상단 원점) x=300 y=100 w=2 h=18, 아이콘 36, gap 8.
    # appkit_y = 900 - 100 - 18 = 782; x = 300 + 2 + 8 = 310; y = 782 + (18-36)/2 = 773
    x, y = hud_overlay.caret_icon_origin((300.0, 100.0, 2.0, 18.0), 900.0, 36.0, gap=8.0)
    assert x == 310.0
    assert y == 773.0


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
