import pytest

import hotkeys


def test_normalize_hotkey_orders_modifiers_before_regular_key():
    assert hotkeys.normalize_hotkey("space+shift+cmd") == "shift+cmd+space"


def test_normalize_hotkey_accepts_single_and_combo_keys():
    assert hotkeys.normalize_hotkey("f8") == "f8"
    assert hotkeys.normalize_hotkey("alt+space") == "alt+space"
    assert hotkeys.normalize_hotkey("cmd_r") == "cmd_r"


def test_normalize_hotkey_rejects_multiple_regular_keys():
    with pytest.raises(ValueError):
        hotkeys.normalize_hotkey("k+space")
