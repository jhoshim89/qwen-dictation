# test_dashboard_paths.py
import json
import os
import app_paths
import dashboard
import dictation_history


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


def test_dashboard_serves_bundled_brand_assets():
    client = dashboard.flask_app.test_client()
    assert client.get("/assets/logo-mark.svg").status_code == 200
    assert client.get("/assets/fonts/PretendardVariable.woff2").status_code == 200


def test_dashboard_assets_route_blocks_parent_directory_escape():
    client = dashboard.flask_app.test_client()
    assert client.get("/assets/../dictionary.json").status_code == 404


def test_dashboard_history_correction_candidate_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "history_path", lambda: str(tmp_path / "history.json"))
    monkeypatch.setattr(app_paths, "vocabulary_candidates_path", lambda: str(tmp_path / "candidates.json"))
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "vocabulary.json"))
    entry = dictation_history.add_history("큐엔 테스트")
    client = dashboard.flask_app.test_client()
    response = client.post(
        f"/api/history/{entry['id']}/correction",
        json={"corrected_text": "Qwen 테스트"},
    )
    assert response.get_json() == {"candidates": ["Qwen"]}
    accepted = client.post("/api/vocabulary/candidates/accept", json={"term": "Qwen"})
    assert accepted.status_code == 200
    assert accepted.get_json()["vocabulary"] == ["Qwen"]
