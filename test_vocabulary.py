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


def test_build_context_caps_term_count():
    words = [f"w{i}" for i in range(40)]
    terms = vocabulary.build_context(words).split(", ")
    assert len(terms) == vocabulary.MAX_CONTEXT_TERMS
    assert terms[0] == "w0" and terms[-1] == "w23"


def test_build_context_with_domain():
    assert vocabulary.build_context(["각막", "궤양"], domain="수의안과 진료") == "수의안과 진료, 각막, 궤양"


def test_build_context_domain_only():
    assert vocabulary.build_context([], domain="수의안과 진료") == "수의안과 진료"


def test_build_context_blank_domain_is_backward_compatible():
    assert vocabulary.build_context(["각막", "궤양"], domain="   ") == "각막, 궤양"
    assert vocabulary.build_context(["각막", "궤양"]) == "각막, 궤양"


def test_build_context_domain_not_counted_in_term_limit():
    words = [f"w{i}" for i in range(40)]
    terms = vocabulary.build_context(words, domain="DOM").split(", ")
    assert terms[0] == "DOM"
    assert len(terms) == vocabulary.MAX_CONTEXT_TERMS + 1   # domain + 24 terms
    assert terms[1] == "w0" and terms[-1] == "w23"
