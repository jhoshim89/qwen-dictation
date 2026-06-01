import importlib.util
from pynput import keyboard


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_key_from_name_known():
    wd = _load()
    assert wd.key_from_name("alt_r") == keyboard.Key.alt_r
    assert wd.key_from_name("cmd_r") == keyboard.Key.cmd_r
    assert wd.key_from_name("ctrl_r") == keyboard.Key.ctrl_r
    assert wd.key_from_name("shift_r") == keyboard.Key.shift_r


def test_key_from_name_unknown_falls_back():
    wd = _load()
    assert wd.key_from_name("nope") == keyboard.Key.alt_r


def test_validate_rejects_same_keys_in_multi():
    wd = _load()
    ok, _ = wd.validate_hotkey_config("multi", "cmd_r", "cmd_r")
    assert ok is False


def test_validate_accepts_distinct_multi():
    wd = _load()
    ok, err = wd.validate_hotkey_config("multi", "alt_r", "cmd_r")
    assert ok is True and err == ""


def test_validate_rejects_unknown_mode():
    wd = _load()
    ok, _ = wd.validate_hotkey_config("weird", "alt_r", "cmd_r")
    assert ok is False


def test_multi_listener_accepts_custom_keys():
    wd = _load()
    lis = wd.MultiHotkeyListener(object(), hold_key=keyboard.Key.shift_r, toggle_key=keyboard.Key.ctrl_r)
    assert lis.hold_key == keyboard.Key.shift_r
    assert lis.toggle_key == keyboard.Key.ctrl_r


def test_multi_listener_defaults():
    wd = _load()
    lis = wd.MultiHotkeyListener(object())
    assert lis.hold_key == keyboard.Key.alt_r
    assert lis.toggle_key == keyboard.Key.cmd_r


def test_app_config_has_hotkey_defaults(tmp_path, monkeypatch):
    import app_config
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "config_path", lambda: str(cfg_file))
    cfg = app_config.load_config()
    assert cfg["hotkey_mode"] == "multi"
    assert cfg["hold_key"] == "alt_r"
    assert cfg["toggle_key"] == "cmd_r"


def test_build_key_listener_selects_type():
    wd = _load()

    class A:
        hotkey_mode = "multi"
        hold_key = "shift_r"
        toggle_key = "cmd_r"
        key_combination = "cmd_l+alt"
    a = A()
    a.build_key_listener = wd.StatusBarApp.build_key_listener.__get__(a, A)
    kl = a.build_key_listener()
    assert isinstance(kl, wd.MultiHotkeyListener)
    assert kl.hold_key == keyboard.Key.shift_r

    a.hotkey_mode = "double"
    assert isinstance(a.build_key_listener(), wd.DoubleCommandKeyListener)

    a.hotkey_mode = "single"
    assert isinstance(a.build_key_listener(), wd.GlobalKeyListener)


def test_api_config_sets_and_applies_hotkeys(monkeypatch):
    import dashboard

    class FakeApp:
        mode = "streaming"
        current_language = "ko"
        languages = ["ko", "en"]
        k_double_cmd = False
        selected_model = "1.7b"
        stream_interval = 1.2
        max_time = 0
        started = False
        hotkey_mode = "multi"
        hold_key = "alt_r"
        toggle_key = "cmd_r"
        applied = 0
        saved = 0

        def save_settings(self):
            self.saved += 1

        def apply_hotkey_config(self):
            self.applied += 1

        def sync_menu_state(self):
            pass
    fake = FakeApp()
    dashboard.app_instance = fake
    client = dashboard.flask_app.test_client()

    r = client.post("/api/config", json={"hotkey_mode": "multi", "hold_key": "shift_r", "toggle_key": "cmd_r"})
    assert r.status_code == 200
    assert fake.hold_key == "shift_r"
    assert fake.applied == 1

    before = fake.applied
    r2 = client.post("/api/config", json={"hotkey_mode": "multi", "hold_key": "cmd_r", "toggle_key": "cmd_r"})
    assert r2.status_code == 400
    assert fake.applied == before
