# test_dictionary_seed.py
import json
import os
import importlib.util

import app_paths


def _load_main_module():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_creates_user_dictionary(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)

    wd = _load_main_module()
    wd.ensure_dictionary()

    user_dict = app_paths.dictionary_path()
    assert os.path.exists(user_dict)
    with open(user_dict, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_apply_dictionary_uses_user_path(tmp_path, monkeypatch):
    fake_home = tmp_path / "home2"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)

    wd = _load_main_module()
    os.makedirs(app_paths.user_data_dir(), exist_ok=True)
    with open(app_paths.dictionary_path(), "w", encoding="utf-8") as f:
        json.dump({"큐엔": "Qwen"}, f, ensure_ascii=False)

    assert wd.apply_dictionary("큐엔 테스트") == "Qwen 테스트"
