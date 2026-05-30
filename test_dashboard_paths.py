# test_dashboard_paths.py
import json
import os
import app_paths
import dashboard


def test_dashboard_get_dictionary_reads_user_path(tmp_path, monkeypatch):
    fake_home = tmp_path / "h"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)
    os.makedirs(app_paths.user_data_dir(), exist_ok=True)
    with open(app_paths.dictionary_path(), "w", encoding="utf-8") as f:
        json.dump({"맥북": "MacBook"}, f, ensure_ascii=False)

    client = dashboard.flask_app.test_client()
    resp = client.get("/api/dictionary")
    assert resp.status_code == 200
    assert resp.get_json().get("맥북") == "MacBook"


def test_dashboard_post_dictionary_writes_user_path(tmp_path, monkeypatch):
    fake_home = tmp_path / "h2"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)

    client = dashboard.flask_app.test_client()
    resp = client.post("/api/dictionary", json={"지피티": "GPT"})
    assert resp.status_code == 200
    with open(app_paths.dictionary_path(), encoding="utf-8") as f:
        assert json.load(f).get("지피티") == "GPT"
