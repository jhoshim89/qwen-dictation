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
        self.hold_send_enter = False
        self.log = []

    def start_app(self, _):
        self.started = True
        self.log.append(("start", True))

    def stop_app(self, _, finalize=True, send_enter=False):
        self.started = False
        self.log.append(("stop", finalize, send_enter))


class FakeRecorder:
    def __init__(self):
        self.rebaselined = 0
        self.self_type_guard_until = 0.0

    def rebaseline(self):
        self.rebaselined += 1


class EditApp(FakeApp):
    def __init__(self, mode="stop"):
        super().__init__()
        self.edit_interrupt_mode = mode
        self.recorder = FakeRecorder()


def test_manual_edit_continue_rebaselines_and_keeps_session():
    wd = _load()
    app = EditApp("continue")
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)  # toggle 시작
    lis.on_key_press(keyboard.KeyCode(char="a"))  # 사용자가 직접 'a' 입력
    assert app.recorder.rebaselined == 1
    assert app.started is True  # 세션 유지
    assert app.log == [("start", True)]


def test_manual_edit_stop_ends_session_without_final_tick():
    wd = _load()
    app = EditApp("stop")
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_press(keyboard.KeyCode(char="x"))
    assert app.started is False
    assert app.recorder.rebaselined == 0
    assert app.log == [("start", True), ("stop", False, False)]


def test_manual_edit_defaults_to_stop():
    wd = _load()
    app = FakeApp()
    app.recorder = FakeRecorder()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_press(keyboard.KeyCode(char="x"))
    assert app.started is False
    assert app.log == [("start", True), ("stop", False, False)]


def test_manual_edit_ignored_during_self_typing_guard():
    wd = _load()
    import time as _t
    app = EditApp("continue")
    app.recorder.self_type_guard_until = _t.time() + 5.0  # 우리가 타이핑 중
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_press(keyboard.KeyCode(char="b"))  # 합성 키로 간주
    assert app.recorder.rebaselined == 0
    assert app.started is True


def test_manual_edit_only_when_session_active():
    wd = _load()
    app = EditApp("continue")
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.KeyCode(char="a"))  # 세션 없음 → 아무 일도 없음
    assert app.recorder.rebaselined == 0
    assert app.started is False


def test_enter_not_treated_as_manual_edit():
    wd = _load()
    app = EditApp("continue")
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_press(keyboard.Key.enter)  # Enter 는 기존 토글 종료 동작
    assert app.recorder.rebaselined == 0
    assert app.started is False
    assert app.log == [("start", True), ("stop", False, False)]


def test_hold_ctrl_starts_streaming_and_release_stops():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.ctrl_r)
    assert app.started is True
    lis.on_key_release(keyboard.Key.ctrl_r)
    assert app.started is False
    assert app.log == [("start", True), ("stop", True, False)]


def test_hold_right_modifier_stops_when_release_is_reported_generic():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app, hold_key="ctrl_r", toggle_key="alt_r")
    lis.on_key_press(keyboard.Key.ctrl_r)
    assert app.started is True
    lis.on_key_release(keyboard.Key.ctrl)
    assert app.started is False
    assert lis.pressed == set()
    assert app.log == [("start", True), ("stop", True, False)]


def test_hold_right_modifier_starts_when_press_is_reported_generic():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app, hold_key="ctrl_r", toggle_key="alt_r")
    lis.on_key_press(keyboard.Key.ctrl)
    assert app.started is False
    assert app.log == []


def test_left_option_does_not_trigger_right_option_toggle():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app, hold_key="ctrl_r", toggle_key="alt_r")
    lis.on_key_press(keyboard.Key.alt)
    assert app.started is False
    assert app.log == []


def test_left_control_does_not_trigger_right_control_hold():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app, hold_key="ctrl_r", toggle_key="alt_r")
    lis.on_key_press(keyboard.Key.ctrl)
    assert app.started is False
    assert app.log == []


def test_left_command_does_not_trigger_right_command_custom_hold():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app, hold_key="cmd_r", toggle_key="alt_r")
    lis.on_key_press(keyboard.Key.cmd)
    assert app.started is False
    assert app.log == []


def test_right_modifier_release_reported_generic_still_stops_existing_hold():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app, hold_key="ctrl_r", toggle_key="alt_r")
    lis.on_key_press(keyboard.Key.ctrl_r)
    assert app.started is True
    lis.on_key_release(keyboard.Key.ctrl)
    assert app.started is False
    assert lis.pressed == set()
    assert app.log == [("start", True), ("stop", True, False)]


def test_hold_start_uses_live_rewrite_mode():
    wd = _load()
    app = EditApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.ctrl_r)
    assert app._live_typing_for_next_start is True
    assert app._append_only_for_next_start is False
    assert app.recorder.defer_typing_until_stop is False
    assert app.recorder.append_only_until_stop is False


def test_toggle_start_keeps_live_typing_mode():
    wd = _load()
    app = EditApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    assert app._live_typing_for_next_start is True
    assert app._append_only_for_next_start is False
    assert app.recorder.defer_typing_until_stop is False
    assert app.recorder.append_only_until_stop is False


def test_hold_autorepeat_does_not_restart():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.ctrl_r)
    lis.on_key_press(keyboard.Key.ctrl_r)
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
    assert app.log == [("start", True), ("stop", True, False)]


def test_toggle_enter_stops_without_final_tick_and_enter_keeps_flowing():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_press(keyboard.Key.enter)
    assert app.started is False
    assert app.log == [("start", True), ("stop", False, False)]


def test_toggle_keypad_enter_stops_without_final_tick():
    wd = _load()
    app = FakeApp()
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_press(keyboard.KeyCode(vk=76))
    assert app.started is False
    assert app.log == [("start", True), ("stop", False, False)]


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
    assert app.log == [("start", True), ("stop", True, False)]


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
    assert app.log == [("start", True), ("stop", True, False)]


def test_hold_release_sends_enter_when_enabled():
    wd = _load()
    app = FakeApp()
    app.hold_send_enter = True
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.ctrl_r)
    lis.on_key_release(keyboard.Key.ctrl_r)
    assert app.log == [("start", True), ("stop", True, True)]


def test_hold_release_no_enter_when_disabled():
    wd = _load()
    app = FakeApp()
    app.hold_send_enter = False
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.ctrl_r)
    lis.on_key_release(keyboard.Key.ctrl_r)
    assert app.log == [("start", True), ("stop", True, False)]


def test_toggle_stop_never_sends_enter_even_when_enabled():
    wd = _load()
    app = FakeApp()
    app.hold_send_enter = True
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.alt_r)
    lis.on_key_release(keyboard.Key.alt_r)
    lis.on_key_press(keyboard.Key.alt_r)  # 다시 눌러 종료
    assert app.log == [("start", True), ("stop", True, False)]


def test_manual_edit_stop_never_sends_enter_even_when_enabled():
    wd = _load()
    app = EditApp("stop")
    app.hold_send_enter = True
    lis = wd.MultiHotkeyListener(app)
    lis.on_key_press(keyboard.Key.ctrl_r)           # 홀드 시작
    lis.on_key_press(keyboard.KeyCode(char="x"))    # 수동 편집 → 종료
    assert app.log == [("start", True), ("stop", False, False)]
