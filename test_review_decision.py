import importlib.util
from pynput import keyboard


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_enter_means_send():
    wd = _load()
    assert wd.decide_review_action(keyboard.Key.enter) == "send"


def test_toggle_key_means_send():
    wd = _load()
    # 녹음 시작/정지에 쓰던 그 키(토글키)를 다시 누르면 = 보내기
    assert wd.decide_review_action(keyboard.Key.cmd_r, toggle_key=keyboard.Key.cmd_r) == "send"


def test_tab_means_insert():
    wd = _load()
    assert wd.decide_review_action(keyboard.Key.tab) == "insert"


def test_esc_means_cancel():
    wd = _load()
    assert wd.decide_review_action(keyboard.Key.esc) == "cancel"


def test_letter_key_is_ignored():
    wd = _load()
    # 결정은 Enter/토글키/Tab/Esc 로만. 그 외 일반 키는 무시(None).
    assert wd.decide_review_action(keyboard.KeyCode(char="a")) is None


def test_space_is_ignored():
    wd = _load()
    assert wd.decide_review_action(keyboard.Key.space) is None


def test_modifier_without_toggle_is_ignored():
    wd = _load()
    # toggle_key 를 안 넘기면 cmd_r 같은 수정키 단독은 결정으로 안 침(None).
    assert wd.decide_review_action(keyboard.Key.cmd_r) is None
    assert wd.decide_review_action(keyboard.Key.shift) is None
    assert wd.decide_review_action(keyboard.Key.alt_r) is None
