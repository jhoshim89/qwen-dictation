# test_vet_terms.py
import vet_terms


def test_vet_terms_is_nonempty_dict():
    assert isinstance(vet_terms.VET_TERMS, dict)
    assert len(vet_terms.VET_TERMS) >= 3


def test_merge_adds_missing_terms():
    existing = {"큐엔": "Qwen"}
    merged = vet_terms.merge_terms_into(existing)
    assert merged["큐엔"] == "Qwen"
    assert "괴양" in merged
    assert merged["괴양"] == "궤양"


def test_merge_does_not_overwrite_user_value():
    existing = {"괴양": "내가직접정한값"}
    merged = vet_terms.merge_terms_into(existing)
    assert merged["괴양"] == "내가직접정한값"


def test_merge_returns_new_dict_not_mutate():
    existing = {"큐엔": "Qwen"}
    merged = vet_terms.merge_terms_into(existing)
    assert "괴양" not in existing
    assert merged is not existing
