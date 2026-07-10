# test_dashboard_paths.py
import json
import os
import app_paths
import dashboard
import dictation_history


def _headers():
    return {"X-Qwen-Token": dashboard._API_TOKEN}


def test_dashboard_get_vocabulary_reads_user_path(tmp_path, monkeypatch):
    fake_home = tmp_path / "h"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)
    os.makedirs(app_paths.user_data_dir(), exist_ok=True)
    with open(app_paths.vocabulary_path(), "w", encoding="utf-8") as f:
        json.dump(["MacBook"], f, ensure_ascii=False)

    client = dashboard.flask_app.test_client()
    resp = client.get("/api/vocabulary", headers=_headers())
    assert resp.status_code == 200
    assert "MacBook" in resp.get_json()


def test_dashboard_post_vocabulary_writes_user_path(tmp_path, monkeypatch):
    fake_home = tmp_path / "h2"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)

    client = dashboard.flask_app.test_client()
    resp = client.post("/api/vocabulary", json=["GPT"], headers=_headers())
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

    resp = dashboard.flask_app.test_client().get("/api/debug", headers=_headers())

    assert resp.status_code == 200
    assert resp.get_json() == {"events": []}


def test_dashboard_debug_returns_recorder_events(monkeypatch):
    from types import SimpleNamespace
    recorder = SimpleNamespace(debug_events=[{"reason": "below_gate", "peak": 10}])
    monkeypatch.setattr(dashboard, "app_instance", SimpleNamespace(recorder=recorder))

    resp = dashboard.flask_app.test_client().get("/api/debug", headers=_headers())

    assert resp.status_code == 200
    assert resp.get_json() == {"events": [{"reason": "below_gate", "peak": 10}]}


def test_dashboard_status_includes_capture_health(monkeypatch):
    from types import SimpleNamespace
    recorder = SimpleNamespace(
        capture_health=lambda: {
            "ready": True,
            "capture_on": True,
            "thread_alive": True,
            "last_frame_age_ms": 12,
        }
    )
    monkeypatch.setattr(
        dashboard,
        "app_instance",
        SimpleNamespace(started=True, elapsed_time=2, processing_active=False, recorder=recorder),
    )

    payload = dashboard.flask_app.test_client().get(
        "/api/status", headers=_headers()
    ).get_json()

    assert payload["capture"]["ready"] is True
    assert payload["capture"]["last_frame_age_ms"] == 12


def test_dashboard_selftest_rejects_while_dictating(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(
        dashboard,
        "app_instance",
        SimpleNamespace(started=True, processing_active=False, recorder=SimpleNamespace()),
    )

    response = dashboard.flask_app.test_client().post(
        "/api/selftest", json={"seconds": 1}, headers=_headers()
    )

    assert response.status_code == 409


def test_dashboard_history_correction_candidate_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "history_path", lambda: str(tmp_path / "history.json"))
    monkeypatch.setattr(app_paths, "vocabulary_candidates_path", lambda: str(tmp_path / "candidates.json"))
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "vocabulary.json"))
    entry = dictation_history.add_history("큐엔 테스트")
    client = dashboard.flask_app.test_client()
    response = client.post(
        f"/api/history/{entry['id']}/correction",
        json={"corrected_text": "Qwen 테스트"},
        headers=_headers(),
    )
    assert response.get_json() == {"candidates": ["Qwen"]}
    accepted = client.post(
        "/api/vocabulary/candidates/accept", json={"term": "Qwen"}, headers=_headers()
    )
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
    resp = client.post(
        "/api/config", json={"hud_mode": "pinned"}, headers=_headers()
    )
    assert resp.status_code == 200
    assert fake.hud_mode == "pinned"
    assert client.get("/api/config", headers=_headers()).get_json()["hud_mode"] == "pinned"


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
    client.post("/api/config", json={"hud_mode": "bogus"}, headers=_headers())
    assert fake.hud_mode == "pill"


def test_dashboard_api_rejects_missing_token():
    response = dashboard.flask_app.test_client().get("/api/status")

    assert response.status_code == 403


def test_dashboard_api_rejects_untrusted_host_and_origin():
    client = dashboard.flask_app.test_client()

    bad_host = client.get(
        "/api/status", headers={**_headers(), "Host": "attacker.example"}
    )
    bad_origin = client.post(
        "/api/history/clear",
        json={},
        headers={**_headers(), "Origin": "https://attacker.example"},
    )

    assert bad_host.status_code == 403
    assert bad_origin.status_code == 403


def test_dashboard_api_requires_json_for_state_changes():
    response = dashboard.flask_app.test_client().post(
        "/api/history/clear", data="", headers=_headers()
    )

    assert response.status_code == 415


def test_dashboard_page_embeds_session_token():
    response = dashboard.flask_app.test_client().get("/")

    assert response.status_code == 200
    assert dashboard._API_TOKEN in response.get_data(as_text=True)


def test_dangerous_dictate_test_api_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(dashboard, "_TEST_API_ENABLED", False)

    response = dashboard.flask_app.test_client().post(
        "/api/dictate_test", json={}, headers=_headers()
    )

    assert response.status_code == 404


def test_dashboard_history_clear_removes_saved_transcripts(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "history_path", lambda: str(tmp_path / "history.json"))
    dictation_history.add_history("민감한 받아쓰기")

    response = dashboard.flask_app.test_client().post(
        "/api/history/clear", json={}, headers=_headers()
    )

    assert response.status_code == 200
    assert dictation_history.load_history() == []


def test_selftest_releases_audio_resources_after_read_error(monkeypatch):
    from types import SimpleNamespace
    import pyaudio

    events = []

    class FakeStream:
        def read(self, *_args, **_kwargs):
            raise RuntimeError("read failed")

        def stop_stream(self):
            events.append("stop")

        def close(self):
            events.append("close")

    class FakePyAudio:
        def get_device_count(self):
            return 0

        def get_default_input_device_info(self):
            return {"index": 0, "name": "Default Mic"}

        def open(self, **_kwargs):
            return FakeStream()

        def terminate(self):
            events.append("terminate")

    monkeypatch.setattr(pyaudio, "PyAudio", FakePyAudio)
    monkeypatch.setattr(
        dashboard,
        "app_instance",
        SimpleNamespace(
            started=False,
            processing_active=False,
            input_device="",
            recorder=SimpleNamespace(),
            set_processing=lambda active: events.append(("processing", active)),
        ),
    )

    response = dashboard.flask_app.test_client().post(
        "/api/selftest", json={"seconds": 1}, headers=_headers()
    )

    assert response.status_code == 500
    assert events == [
        ("processing", True),
        "stop",
        "close",
        "terminate",
        ("processing", False),
    ]
    assert dashboard._DIAGNOSTIC_LOCK.acquire(blocking=False) is True
    dashboard._DIAGNOSTIC_LOCK.release()
