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
        self.mode = None
        self.log = []

    def begin_session(self, mode):
        self.mode = mode
        self.started = True
        self.log.append(("begin", mode))

    def stop_app(self, _):
        self.started = False
        self.log.append(("stop",))


def test_hold_cmd_starts_streaming_and_release_stops():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.cmd_r)
    assert app.started is True
    assert app.mode == wd.MODE_STREAMING
    lis.on_key_release(keyboard.Key.cmd_r)
    assert app.started is False
    assert app.log == [("begin", wd.MODE_STREAMING), ("stop",)]


def test_hold_autorepeat_does_not_restart():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.cmd_r)
    lis.on_key_press(keyboard.Key.cmd_r)
    assert app.log == [("begin", wd.MODE_STREAMING)]


def test_toggle_alt_starts_streaming_and_repress_stops():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    assert app.started is True and app.mode == wd.MODE_STREAMING
    lis.on_key_release(keyboard.Key.alt_r)
    assert app.started is True  # 토글은 release로 멈추지 않음
    lis.on_key_press(keyboard.Key.alt_r)
    assert app.started is False
    assert app.log == [("begin", wd.MODE_STREAMING), ("stop",)]


def test_other_key_ignored_while_recording():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_press(keyboard.Key.cmd_r)
    assert app.mode == wd.MODE_STREAMING
    assert app.log == [("begin", wd.MODE_STREAMING)]


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
