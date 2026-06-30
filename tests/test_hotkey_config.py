import importlib.util
from types import SimpleNamespace

from pynput import keyboard


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_token_from_key_known():
    wd = _load()
    assert wd.token_from_key(keyboard.Key.alt_r) == "alt_r"
    assert wd.token_from_key(keyboard.Key.cmd_r) == "cmd_r"
    assert wd.token_from_key(keyboard.Key.space) == "space"
    assert wd.token_from_key(keyboard.KeyCode(vk=76)) == "enter"
    assert wd.token_from_key(keyboard.KeyCode(char="K")) == "k"
    assert wd.token_from_key(wd.HOTKEY_FN) == wd.HOTKEY_FN


def test_token_from_key_unknown_returns_none():
    wd = _load()
    assert wd.token_from_key(object()) is None


def test_validate_rejects_same_keys():
    wd = _load()
    ok, _ = wd.validate_hotkey_config("cmd_r", "cmd_r")
    assert ok is False


def test_validate_accepts_distinct_keys():
    wd = _load()
    ok, err = wd.validate_hotkey_config("alt_r", "cmd_r")
    assert ok is True and err == ""


def test_validate_accepts_modifier_combo_and_function_key():
    wd = _load()
    assert wd.validate_hotkey_config("alt+space", "f8") == (True, "")


def test_validate_rejects_unknown_key():
    wd = _load()
    ok, _ = wd.validate_hotkey_config("weird", "cmd_r")
    assert ok is False


def test_fn_key_transition_reports_press_and_release():
    wd = _load()
    pressed, transition = wd.fn_key_transition(
        wd.kCGEventFlagsChanged, wd.kCGEventFlagMaskSecondaryFn, False
    )
    assert (pressed, transition) == (True, "press")
    pressed, transition = wd.fn_key_transition(wd.kCGEventFlagsChanged, 0, pressed)
    assert (pressed, transition) == (False, "release")


def test_fn_key_transition_ignores_unrelated_events():
    wd = _load()
    assert wd.fn_key_transition(999, wd.kCGEventFlagMaskSecondaryFn, False) == (False, None)


def test_multi_listener_accepts_custom_keys():
    wd = _load()
    lis = wd.MultiHotkeyListener(object(), hold_key="shift_r+k", toggle_key="ctrl_r+space")
    assert lis.hold_key == "shift_r+k"
    assert lis.toggle_key == "ctrl_r+space"


def test_multi_listener_defaults():
    wd = _load()
    lis = wd.MultiHotkeyListener(object())
    assert lis.hold_key == "ctrl_r"
    assert lis.toggle_key == "alt_r"


def test_app_config_has_hotkey_defaults(tmp_path, monkeypatch):
    import app_config
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "config_path", lambda: str(cfg_file))
    cfg = app_config.load_config()
    assert cfg["hold_key"] == "ctrl_r"
    assert cfg["toggle_key"] == "alt_r"


def test_build_key_listener_uses_multi_listener():
    wd = _load()

    class A:
        hold_key = "shift_r"
        toggle_key = "cmd_r"
    a = A()
    a.build_key_listener = wd.StatusBarApp.build_key_listener.__get__(a, A)
    kl = a.build_key_listener()
    assert isinstance(kl, wd.MultiHotkeyListener)
    assert kl.hold_key == "shift_r"

def test_api_config_sets_and_applies_hotkeys(monkeypatch):
    import dashboard

    class FakeApp:
        current_language = "ko"
        languages = ["ko", "en"]
        max_time = 0
        started = False
        hold_key = "alt_r"
        toggle_key = "cmd_r"
        min_volume = 35
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

    r = client.post("/api/config", json={"hold_key": "shift_r+k", "toggle_key": "cmd_r+space"})
    assert r.status_code == 200
    assert fake.hold_key == "shift_r+k"
    assert fake.applied == 1

    before = fake.applied
    r2 = client.post("/api/config", json={"hold_key": "cmd_r", "toggle_key": "cmd_r"})
    assert r2.status_code == 400
    assert fake.applied == before


def test_api_config_sets_min_volume():
    import dashboard

    class FakeTranscriber:
        min_volume = 35
        asr_engine = "qwen"

        def set_engine(self, engine):
            self.asr_engine = engine

    class FakeRecorder:
        transcriber = FakeTranscriber()

    class FakeApp:
        current_language = "ko"
        languages = ["ko", "en"]
        max_time = 300
        input_device = ""
        hold_key = "cmd_r"
        toggle_key = "alt_r"
        min_volume = 35
        asr_engine = "qwen"
        recorder = FakeRecorder()

        def save_settings(self):
            pass

        def sync_menu_state(self):
            pass

    fake = FakeApp()
    dashboard.app_instance = fake
    client = dashboard.flask_app.test_client()

    r = client.post("/api/config", json={"min_volume": 0})
    assert r.status_code == 200
    assert fake.min_volume == 1
    assert fake.recorder.transcriber.min_volume == 1

    r = client.post("/api/config", json={"min_volume": 120})
    assert r.status_code == 200
    assert fake.min_volume == 100

    r = client.post("/api/config", json={"asr_engine": "nemotron"})
    assert r.status_code == 200
    assert fake.asr_engine == "nemotron_mlx"
    assert fake.recorder.transcriber.asr_engine == "nemotron_mlx"

    r = client.post("/api/config", json={"asr_engine": "qwen-original"})
    assert r.status_code == 200
    assert fake.asr_engine == "qwen_original"
    assert fake.recorder.transcriber.asr_engine == "qwen_original"

    r = client.post("/api/config", json={"asr_engine": "google"})
    assert r.status_code == 200
    assert fake.asr_engine == "qwen"
    assert fake.recorder.transcriber.asr_engine == "qwen"


def test_menu_model_change_updates_transcriber_and_checkmark():
    wd = _load()

    class Item:
        state = 0

    class Transcriber:
        asr_engine = "qwen"

        def set_engine(self, engine):
            self.asr_engine = engine

    class App:
        languages = ["ko"]
        current_language = "ko"
        asr_engine = "qwen"
        recorder = SimpleNamespace(transcriber=Transcriber())
        menu = {
            "Language: ko": Item(),
            "Model: Qwen": Item(),
            "Model: Nemotron": Item(),
        }
        saved = 0
        _asr_engine_menu_title = staticmethod(wd.StatusBarApp._asr_engine_menu_title)

        def save_settings(self):
            self.saved += 1

    app = App()
    app.sync_menu_state = wd.StatusBarApp.sync_menu_state.__get__(app, App)
    app.set_asr_engine = wd.StatusBarApp.set_asr_engine.__get__(app, App)
    app.change_asr_engine = wd.StatusBarApp.change_asr_engine.__get__(app, App)

    app.change_asr_engine(SimpleNamespace(engine_id="nemotron"))

    assert app.asr_engine == "nemotron_mlx"
    assert app.recorder.transcriber.asr_engine == "nemotron_mlx"
    assert app.menu["Model: Qwen"].state == 0
    assert app.menu["Model: Nemotron"].state == 1
    assert app.saved == 1


def test_default_keys_are_ctrl_hold_option_toggle():
    import app_config
    cfg = dict(app_config.DEFAULTS)
    assert cfg["hold_key"] == "ctrl_r"     # 홀드 = 오른쪽 Ctrl
    assert cfg["toggle_key"] == "alt_r"    # 토글 = 오른쪽 Option
    assert cfg["min_volume"] == 8           # 이 마이크에서 작은 목소리도 시작되게 하는 기본값


def test_multi_listener_both_triggers_start_app():
    wd = _load()
    starts = []

    class App:
        started = False
        def start_app(self, _): starts.append("start"); self.started = True
        def stop_app(self, _, finalize=True): self.started = False
    app = App()
    lis = wd.MultiHotkeyListener(app, hold_key="cmd_r", toggle_key="alt_r")
    # 홀드(누름) → streaming 시작
    lis.on_key_press(wd.keyboard.Key.cmd_r)
    # 토글(누름) → 이미 시작 중이면 무시되므로, 새 인스턴스로 토글 확인
    app2 = App()
    lis2 = wd.MultiHotkeyListener(app2, hold_key="cmd_r", toggle_key="alt_r")
    lis2.on_key_press(wd.keyboard.Key.alt_r)
    assert starts[0] == "start"
    assert app2.started and starts[-1] == "start"
