import hud_overlay
from types import SimpleNamespace


class _FakePanel:
    def __init__(self):
        self.hidden = 0
        self.shown = 0

    def orderOut_(self, _):
        self.hidden += 1

    def orderFrontRegardless(self):
        self.shown += 1


class _FakeView:
    def __init__(self):
        self.labels = []

    def setLabelText_(self, text):
        self.labels.append(text)


def _overlay(visible=False):
    overlay = object.__new__(hud_overlay.DictationOverlay)
    overlay._panel = _FakePanel()
    overlay._view = _FakeView()
    overlay._visible = visible
    overlay._resizes = []
    overlay._resize_panel = lambda width, height, radius: overlay._resizes.append((width, height, radius))
    overlay._reposition_for_pointer_screen = lambda: None
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
