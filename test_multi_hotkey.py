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
        self.log = []

    def start_app(self, _):
        self.started = True
        self.log.append(("start", True))

    def stop_app(self, _, finalize=True):
        self.started = False
        self.log.append(("stop", finalize))


def test_hold_cmd_starts_streaming_and_release_stops():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.cmd_r)
    assert app.started is True
    lis.on_key_release(keyboard.Key.cmd_r)
    assert app.started is False
    assert app.log == [("start", True), ("stop", True)]


def test_hold_autorepeat_does_not_restart():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.cmd_r)
    lis.on_key_press(keyboard.Key.cmd_r)
    assert app.log == [("start", True)]


def test_toggle_alt_starts_streaming_and_repress_stops():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    assert app.started is True
    lis.on_key_release(keyboard.Key.alt_r)
    assert app.started is True  # 토글은 release로 멈추지 않음
    lis.on_key_press(keyboard.Key.alt_r)
    assert app.started is False
    assert app.log == [("start", True), ("stop", True)]


def test_toggle_enter_stops_without_final_tick_and_enter_keeps_flowing():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_press(keyboard.Key.enter)
    assert app.started is False
    assert app.log == [("start", True), ("stop", False)]


def test_other_key_ignored_while_recording():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_press(keyboard.Key.cmd_r)
    assert app.log == [("start", True)]


def test_release_of_non_owning_key_does_nothing():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_release(keyboard.Key.cmd_r)
    assert app.started is True


def test_unrelated_key_does_nothing():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.KeyCode(char="a"))
    lis.on_key_release(keyboard.KeyCode(char="a"))
    assert app.started is False
    assert app.log == []


def test_hold_combo_starts_after_last_key_and_stops_on_release():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app, hold_key="ctrl+space", toggle_key="f8")
    lis.on_key_press(keyboard.Key.ctrl)
    assert app.started is False
    lis.on_key_press(keyboard.Key.space)
    assert app.started is True
    lis.on_key_release(keyboard.Key.space)
    assert app.log == [("start", True), ("stop", True)]


def test_toggle_combo_fires_once_until_released():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app, hold_key="cmd_r", toggle_key="alt+space")
    lis.on_key_press(keyboard.Key.alt)
    lis.on_key_press(keyboard.Key.space)
    lis.on_key_press(keyboard.Key.space)
    assert app.log == [("start", True)]
    lis.on_key_release(keyboard.Key.space)
    lis.on_key_press(keyboard.Key.space)
    assert app.log == [("start", True), ("stop", True)]
