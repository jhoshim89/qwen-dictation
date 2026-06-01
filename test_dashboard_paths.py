# test_dashboard_paths.py
import json
import os
import app_paths
import dashboard


def test_dashboard_get_vocabulary_reads_user_path(tmp_path, monkeypatch):
    fake_home = tmp_path / "h"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)
    os.makedirs(app_paths.user_data_dir(), exist_ok=True)
    with open(app_paths.vocabulary_path(), "w", encoding="utf-8") as f:
        json.dump(["MacBook"], f, ensure_ascii=False)

    client = dashboard.flask_app.test_client()
    resp = client.get("/api/vocabulary")
    assert resp.status_code == 200
    assert "MacBook" in resp.get_json()


def test_dashboard_post_vocabulary_writes_user_path(tmp_path, monkeypatch):
    fake_home = tmp_path / "h2"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)

    client = dashboard.flask_app.test_client()
    resp = client.post("/api/vocabulary", json=["GPT"])
    assert resp.status_code == 200
    with open(app_paths.vocabulary_path(), encoding="utf-8") as f:
        assert "GPT" in json.load(f)
