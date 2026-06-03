import app_paths
import vocabulary


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "vocabulary.json"))
    vocabulary.save_vocabulary(["Qwen", "각막", "각막", " "])
    assert vocabulary.load_vocabulary() == ["Qwen", "각막"]


def test_load_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "missing.json"))
    assert vocabulary.load_vocabulary() == []


def test_build_context():
    assert vocabulary.build_context(["각막", "궤양"]) == "각막, 궤양"
