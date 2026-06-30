import hud_overlay
from types import SimpleNamespace


class _FakePanel:
    def __init__(self, width=hud_overlay.PANEL_WIDTH):
        self.hidden = 0
        self.shown = 0
        self.ignores_mouse = None
        self.movable = None
        self._width = width

    def frame(self):
        return SimpleNamespace(size=SimpleNamespace(width=self._width))

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


def _overlay(visible=False, width=hud_overlay.PANEL_WIDTH):
    overlay = object.__new__(hud_overlay.DictationOverlay)
    overlay._panel = _FakePanel(width)
    overlay._view = _FakeView()
    overlay._visible = visible
    overlay._resizes = []
    overlay._resize_panel = lambda width, height, radius: overlay._resizes.append((width, height, radius))
    overlay._reposition_for_pointer_screen = lambda: None
    # 라벨 측정은 AppKit 의존이라 테스트마다 결정적 값으로 덮어쓴다(기본은 짧은 라벨).
    overlay._measure_label_width = lambda text: 30.0
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


def test_show_status_keeps_default_width_for_short_label():
    overlay = _overlay(width=hud_overlay.PANEL_WIDTH)
    overlay._measure_label_width = lambda text: 30.0  # LABEL_LEFT+30+LABEL_RIGHT_PAD=84 < 기본 폭
    overlay.show_status("듣는 중")
    assert overlay._view.labels == ["듣는 중"]
    assert overlay._resizes == []
    assert overlay._visible is True


def test_show_status_widens_pill_for_long_label():
    overlay = _overlay(width=hud_overlay.PANEL_WIDTH)
    overlay._measure_label_width = lambda text: 120.0  # 28+18+9+120=175 로 늘어남
    overlay.show_status("모델 불러오는 중…")
    assert overlay._view.labels == ["모델 불러오는 중…"]
    assert overlay._resizes == [
        (175.0, hud_overlay.PANEL_HEIGHT, hud_overlay.BAR_CORNER_RADIUS)
    ]
    assert overlay._visible is True


def test_show_status_pinned_mode_does_not_resize():
    overlay = _overlay()
    overlay._mode = "pinned"
    overlay._measure_label_width = lambda text: 999.0
    overlay.show_status("모델 불러오는 중…")
    # 아이콘(고정) 모드는 라벨을 안 그리므로 폭을 건드리지 않는다.
    assert overlay._resizes == []
    assert overlay._visible is True


def test_pill_width_for_label_keeps_minimum_for_short_text():
    assert hud_overlay.pill_width_for_label(0.0) == hud_overlay.PANEL_WIDTH
    assert hud_overlay.pill_width_for_label(30.0) == hud_overlay.PANEL_WIDTH


def test_pill_width_for_label_grows_for_long_text():
    # 28(양옆 여백) + 18(미터) + 9(간격) + 120(글자) = 175
    assert hud_overlay.pill_width_for_label(120.0) == 175.0


def test_pill_layout_applies_short_label_optical_centering():
    meter_x, label_x = hud_overlay.pill_layout_for_label(hud_overlay.PANEL_WIDTH, 30.0)
    geometric_meter_x = (
        hud_overlay.PANEL_WIDTH
        - (hud_overlay.METER_WIDTH + hud_overlay.METER_LABEL_GAP + 30.0)
    ) / 2.0
    assert meter_x == geometric_meter_x + hud_overlay.PILL_CONTENT_OPTICAL_OFFSET_X
    assert label_x == meter_x + hud_overlay.METER_WIDTH + hud_overlay.METER_LABEL_GAP


def test_pill_layout_keeps_long_label_inside_side_padding():
    meter_x, _ = hud_overlay.pill_layout_for_label(175.0, 120.0)
    assert meter_x == hud_overlay.PILL_SIDE_PAD



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
    assert hud_overlay.PANEL_WIDTH == 104.0
    assert hud_overlay.PANEL_HEIGHT == 44.0
    assert hud_overlay.BOTTOM_OFFSET == 86.0


def test_jelly_bar_heights_expand_with_level_clamp_and_stay_symmetric():
    # Resting bars are short; speaking grows them several-fold so the meter
    # visibly reacts to the voice.
    assert hud_overlay.jelly_bar_heights(-1.0) == (4.0, 8.0, 4.0)
    assert hud_overlay.jelly_bar_heights(0.25) == (8.0, 16.0, 8.0)
    assert hud_overlay.jelly_bar_heights(2.0) == (12.0, 24.0, 12.0)


def test_normalize_hud_mode_accepts_known_and_falls_back():
    assert hud_overlay.normalize_hud_mode("pill") == "pill"
    assert hud_overlay.normalize_hud_mode("pinned") == "pinned"
    # 제거된 모드(옛 'caret'/'cursor')와 미지값은 기본 'pill'로.
    assert hud_overlay.normalize_hud_mode("caret") == "pill"
    assert hud_overlay.normalize_hud_mode("cursor") == "pill"
    assert hud_overlay.normalize_hud_mode("bogus") == "pill"
    assert hud_overlay.normalize_hud_mode(None) == "pill"
    assert hud_overlay.HUD_MODES == ("pill", "pinned")


def test_icon_size_is_small():
    assert hud_overlay.ICON_SIZE == 24.0


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
    overlay._mode = "pinned"
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
