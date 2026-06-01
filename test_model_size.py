import json
import importlib.util

import app_config


def test_stale_0_6b_is_coerced_to_1_7b(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"model_size": "0.6b"}), encoding="utf-8")
    monkeypatch.setattr(app_config, "config_path", lambda: str(cfg_file))
    cfg = app_config.load_config()
    assert cfg["model_size"] == "1.7b"


def test_valid_model_size_preserved(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"model_size": "1.7b"}), encoding="utf-8")
    monkeypatch.setattr(app_config, "config_path", lambda: str(cfg_file))
    assert app_config.load_config()["model_size"] == "1.7b"


def _load_wd():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_default_model_is_1_7b(monkeypatch):
    wd = _load_wd()
    monkeypatch.setattr("sys.argv", ["whisper-dictation.py"])
    args = wd.parse_args()
    assert args.model_size == "1.7b"


def test_cli_rejects_0_6b(monkeypatch):
    wd = _load_wd()
    monkeypatch.setattr("sys.argv", ["whisper-dictation.py", "--model-size", "0.6b"])
    import pytest
    with pytest.raises(SystemExit):
        wd.parse_args()
