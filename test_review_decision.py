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


def test_esc_means_cancel():
    wd = _load()
    assert wd.decide_review_action(keyboard.Key.esc) == "cancel"


def test_letter_key_means_insert():
    wd = _load()
    assert wd.decide_review_action(keyboard.KeyCode(char="a")) == "insert"


def test_space_means_insert():
    wd = _load()
    assert wd.decide_review_action(keyboard.Key.space) == "insert"


def test_pure_modifier_is_ignored():
    wd = _load()
    # 수정키 단독(shift/cmd 등)은 결정으로 치지 않는다 → None
    assert wd.decide_review_action(keyboard.Key.shift) is None
    assert wd.decide_review_action(keyboard.Key.cmd) is None
    assert wd.decide_review_action(keyboard.Key.cmd_r) is None
    assert wd.decide_review_action(keyboard.Key.alt) is None
    assert wd.decide_review_action(keyboard.Key.ctrl) is None
