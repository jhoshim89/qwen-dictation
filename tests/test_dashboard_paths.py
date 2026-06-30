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


def test_resource_path_prefers_app_resources_over_frameworks(tmp_path, monkeypatch):
    app = tmp_path / "Qwen Dictation.app"
    resources = app / "Contents" / "Resources" / "templates"
    frameworks = app / "Contents" / "Frameworks"
    macos = app / "Contents" / "MacOS"
    resources.mkdir(parents=True)
    frameworks.mkdir(parents=True)
    macos.mkdir(parents=True)
    (resources / "dashboard.html").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app_paths.sys, "_MEIPASS", str(frameworks), raising=False)
    monkeypatch.setattr(app_paths.sys, "executable", str(macos / "Qwen Dictation"))

    assert app_paths.resource_path("templates", "dashboard.html") == str(resources / "dashboard.html")

def test_dashboard_serves_bundled_brand_assets():
    client = dashboard.flask_app.test_client()
    assert client.get("/assets/logo-mark.svg").status_code == 200
    assert client.get("/assets/fonts/PretendardVariable.woff2").status_code == 200


def test_dashboard_assets_route_blocks_parent_directory_escape():
    client = dashboard.flask_app.test_client()
    assert client.get("/assets/../dictionary.json").status_code == 404


def test_dashboard_debug_returns_empty_without_recorder(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(dashboard, "app_instance", SimpleNamespace())

    resp = dashboard.flask_app.test_client().get("/api/debug")

    assert resp.status_code == 200
    assert resp.get_json() == {"events": []}


def test_dashboard_debug_returns_recorder_events(monkeypatch):
    from types import SimpleNamespace
    recorder = SimpleNamespace(debug_events=[{"reason": "below_gate", "peak": 10}])
    monkeypatch.setattr(dashboard, "app_instance", SimpleNamespace(recorder=recorder))

    resp = dashboard.flask_app.test_client().get("/api/debug")

    assert resp.status_code == 200
    assert resp.get_json() == {"events": [{"reason": "below_gate", "peak": 10}]}


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


def test_dashboard_config_hud_mode_roundtrip(monkeypatch):
    from types import SimpleNamespace
    fake = SimpleNamespace(
        current_language="ko", languages=["ko", "en", "auto"],
        max_time=300, input_device="", hold_key="cmd_r", toggle_key="alt_r",
        min_volume=35, edit_interrupt_mode="continue", hold_send_enter=True,
        asr_engine="qwen", domain_context="", hud_mode="pill", hud_pin_x=None, hud_pin_y=None,
    )
    fake.sync_menu_state = lambda: None
    fake.save_settings = lambda: None
    monkeypatch.setattr(dashboard, "app_instance", fake)

    client = dashboard.flask_app.test_client()
    resp = client.post("/api/config", json={"hud_mode": "pinned"})
    assert resp.status_code == 200
    assert fake.hud_mode == "pinned"
    assert client.get("/api/config").get_json()["hud_mode"] == "pinned"


def test_dashboard_config_hud_mode_rejects_unknown(monkeypatch):
    from types import SimpleNamespace
    fake = SimpleNamespace(
        current_language="ko", languages=["ko"], max_time=300, input_device="",
        hold_key="cmd_r", toggle_key="alt_r", min_volume=35,
        asr_engine="qwen", edit_interrupt_mode="continue", hold_send_enter=True, domain_context="",
        hud_mode="pill", hud_pin_x=None, hud_pin_y=None,
    )
    fake.sync_menu_state = lambda: None
    fake.save_settings = lambda: None
    monkeypatch.setattr(dashboard, "app_instance", fake)

    client = dashboard.flask_app.test_client()
    client.post("/api/config", json={"hud_mode": "bogus"})
    assert fake.hud_mode == "pill"
