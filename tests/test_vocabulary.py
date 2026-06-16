import app_paths
import vocabulary


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "vocabulary.json"))
    vocabulary.save_vocabulary(["Qwen", "각막", "각막", " "])
    assert vocabulary.load_vocabulary() == ["Qwen", "각막"]


def test_load_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "missing.json"))
    assert vocabulary.load_vocabulary() == []


def test_build_context_labels_terms_as_metadata():
    # 등록 단어를 그냥 나열하면 모델이 '받아쓸 목록'으로 착각해 출력에 흘린다(echo).
    # '전문 용어:' 머리표를 붙여 메타데이터(참고 사전)로 인식시켜 leakage 를 막는다.
    assert vocabulary.build_context(["각막", "궤양"]) == "전문 용어: 각막, 궤양"


def test_build_context_label_with_domain():
    # 분야 문장은 앞에 두고, 단어 목록만 '전문 용어:' 로 게이팅한다.
    assert (
        vocabulary.build_context(["각막", "궤양"], domain="수의안과 진료")
        == "수의안과 진료. 전문 용어: 각막, 궤양"
    )


def test_build_context_no_label_when_no_terms():
    # 단어가 없으면 머리표도 없다(빈 라벨만 남으면 안 됨).
    assert vocabulary.build_context([]) == ""
    assert vocabulary.build_context([], domain="수의안과 진료") == "수의안과 진료"


def test_build_context_caps_term_count():
    words = [f"w{i}" for i in range(40)]
    out = vocabulary.build_context(words)
    expected = "전문 용어: " + ", ".join(f"w{i}" for i in range(vocabulary.MAX_CONTEXT_TERMS))
    assert out == expected   # w0..w23 만, 그 뒤는 잘림


def test_build_context_with_domain():
    assert (
        vocabulary.build_context(["각막", "궤양"], domain="수의안과 진료")
        == "수의안과 진료. 전문 용어: 각막, 궤양"
    )


def test_build_context_domain_only():
    assert vocabulary.build_context([], domain="수의안과 진료") == "수의안과 진료"


def test_build_context_blank_domain_is_backward_compatible():
    # 빈 domain 은 domain 없는 것과 동일하게 처리(머리표만 붙은 단어 라벨).
    assert vocabulary.build_context(["각막", "궤양"], domain="   ") == "전문 용어: 각막, 궤양"
    assert vocabulary.build_context(["각막", "궤양"]) == "전문 용어: 각막, 궤양"


def test_build_context_domain_not_counted_in_term_limit():
    words = [f"w{i}" for i in range(40)]
    out = vocabulary.build_context(words, domain="DOM")
    expected = "DOM. 전문 용어: " + ", ".join(f"w{i}" for i in range(vocabulary.MAX_CONTEXT_TERMS))
    assert out == expected   # domain 은 한도에 안 들어가고, 단어는 w0..w23 만
