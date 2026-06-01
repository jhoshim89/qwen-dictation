import hud_overlay


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
        self.review_texts = []
        self.labels = []

    def setReviewText_(self, text):
        self.review_texts.append(text)

    def setLabelText_(self, text):
        self.labels.append(text)


def _overlay(visible=False, review_mode=False):
    overlay = object.__new__(hud_overlay.DictationOverlay)
    overlay._panel = _FakePanel()
    overlay._view = _FakeView()
    overlay._visible = visible
    overlay._review_mode = review_mode
    overlay._resizes = []
    overlay._resize_panel = lambda width, height: overlay._resizes.append((width, height))
    return overlay


def test_hide_idle_overlay_does_not_mutate_window_frame():
    overlay = _overlay()
    overlay.hide()
    assert overlay._resizes == []
    assert overlay._view.review_texts == []
    assert overlay._panel.hidden == 0


def test_hide_review_overlay_restores_recording_size_once():
    overlay = _overlay(visible=True, review_mode=True)
    overlay.hide()
    assert overlay._resizes == [(hud_overlay.PANEL_WIDTH, hud_overlay.PANEL_HEIGHT)]
    assert overlay._view.review_texts == [None]
    assert overlay._panel.hidden == 1


def test_show_status_updates_label_without_resizing_panel():
    overlay = _overlay()
    overlay.show_status("받아쓰기 변환 중")
    assert overlay._view.labels == ["받아쓰기 변환 중"]
    assert overlay._resizes == []
    assert overlay._visible is True
