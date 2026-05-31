# test_app_config.py
import json
import os
import app_config


def test_defaults_have_required_keys():
    for k in ["mode", "language", "model_size", "stream_interval", "max_time"]:
        assert k in app_config.DEFAULTS


def test_load_returns_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "config_path", lambda: str(tmp_path / "config.json"))
    cfg = app_config.load_config()
    assert cfg["model_size"] == app_config.DEFAULTS["model_size"]
    assert cfg["mode"] == app_config.DEFAULTS["mode"]


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "config_path", lambda: str(tmp_path / "config.json"))
    app_config.save_config({"mode": "batch_paste", "model_size": "1.7b",
                            "language": "ko", "stream_interval": 1.5, "max_time": 0})
    cfg = app_config.load_config()
    assert cfg["mode"] == "batch_paste"
    assert cfg["model_size"] == "1.7b"
    assert cfg["max_time"] == 0


def test_load_ignores_unknown_keys_and_fills_missing(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "config_path", lambda: str(p))
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"mode": "streaming", "bogus": 123}, f)
    cfg = app_config.load_config()
    assert cfg["mode"] == "streaming"
    assert "bogus" not in cfg
    assert cfg["model_size"] == app_config.DEFAULTS["model_size"]


def test_load_handles_corrupt_file(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "config_path", lambda: str(p))
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ not valid json")
    cfg = app_config.load_config()
    assert cfg["model_size"] == app_config.DEFAULTS["model_size"]
