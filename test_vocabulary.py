import json

import app_paths
import vocabulary


def _point_to_tmp(tmp_path, monkeypatch):
    vp = tmp_path / "vocabulary.json"
    dp = tmp_path / "dictionary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    monkeypatch.setattr(app_paths, "dictionary_path", lambda: str(dp))
    return vp, dp


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    vocabulary.save_vocabulary(["Qwen", "각막"])
    assert vocabulary.load_vocabulary() == ["Qwen", "각막"]


def test_load_missing_returns_empty(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    assert vocabulary.load_vocabulary() == []


def test_build_context_joins_with_comma(tmp_path, monkeypatch):
    assert vocabulary.build_context(["각막", "궤양"]) == "각막, 궤양"
    assert vocabulary.build_context([]) == ""


def test_ensure_seeds_from_dictionary_values_and_vet_terms(tmp_path, monkeypatch):
    vp, dp = _point_to_tmp(tmp_path, monkeypatch)
    dp.write_text(json.dumps({"큐엔": "Qwen", "각막": "각막"}), encoding="utf-8")
    vocabulary.ensure_vocabulary()
    words = vocabulary.load_vocabulary()
    assert "Qwen" in words          # dictionary 의 값
    assert "각막" in words
    assert "궤양" in words          # vet_terms 의 값(괴양->궤양)
    assert len(words) == len(set(words))  # 중복 없음


def test_ensure_does_not_overwrite_existing(tmp_path, monkeypatch):
    vp, dp = _point_to_tmp(tmp_path, monkeypatch)
    vp.write_text(json.dumps(["내단어"]), encoding="utf-8")
    vocabulary.ensure_vocabulary()
    assert vocabulary.load_vocabulary() == ["내단어"]


def test_api_vocabulary_get_post(tmp_path, monkeypatch):
    import dashboard
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "vocabulary.json"))
    client = dashboard.flask_app.test_client()
    r = client.post("/api/vocabulary", json=["Qwen", "각막", "각막"])
    assert r.status_code == 200
    assert vocabulary.load_vocabulary() == ["Qwen", "각막"]  # 중복 제거 저장
    g = client.get("/api/vocabulary")
    assert g.get_json() == ["Qwen", "각막"]
