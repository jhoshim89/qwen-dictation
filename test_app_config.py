import json

import app_config


def test_defaults_only_have_live_settings():
    assert set(app_config.DEFAULTS) == {
        "language", "max_time", "input_device", "hold_key", "toggle_key",
        "min_volume", "edit_interrupt_mode", "max_time_zero_migrated",
        "hold_send_enter",
    }
    assert app_config.DEFAULTS["max_time"] == 300
    assert app_config.DEFAULTS["min_volume"] == 35
    assert app_config.DEFAULTS["edit_interrupt_mode"] == "continue"
    assert app_config.DEFAULTS["hold_send_enter"] is True


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "config_path", lambda: str(tmp_path / "config.json"))
    app_config.save_config({"language": "en", "max_time": 0, "input_device": "",
                            "hold_key": "ctrl_r", "toggle_key": "alt_r",
                            "min_volume": 12})
    cfg = app_config.load_config()
    assert cfg["language"] == "en"
    assert cfg["max_time"] == 0
    assert cfg["hold_key"] == "ctrl_r"
    assert cfg["min_volume"] == 12


def test_legacy_zero_is_migrated_once(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"max_time": 0}), encoding="utf-8")
    monkeypatch.setattr(app_config, "config_path", lambda: str(path))
    assert app_config.load_config()["max_time"] == 300
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["max_time_zero_migrated"] is True
    app_config.save_config({**saved, "max_time": 0})
    assert app_config.load_config()["max_time"] == 0


def test_unknown_legacy_keys_are_dropped_on_save(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "config_path", lambda: str(path))
    app_config.save_config({"mode": "batch_paste", "model_size": "0.6b"})
    assert "mode" not in json.loads(path.read_text(encoding="utf-8"))


def test_hold_send_enter_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "config_path", lambda: str(tmp_path / "config.json"))
    app_config.save_config({"hold_send_enter": False})
    assert app_config.load_config()["hold_send_enter"] is False
