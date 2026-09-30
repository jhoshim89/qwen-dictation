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


def test_save_drops_overlong_terms(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "vocabulary.json"))
    long_term = "가" * (vocabulary.MAX_TERM_CHARS + 1)
    assert vocabulary.save_vocabulary(["각막", long_term]) == ["각막"]


def test_save_caps_total_term_count(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "vocabulary.json"))
    saved = vocabulary.save_vocabulary([f"w{i}" for i in range(vocabulary.MAX_VOCABULARY_TERMS + 50)])
    assert len(saved) == vocabulary.MAX_VOCABULARY_TERMS
    assert vocabulary.load_vocabulary() == saved


def test_append_vocabulary_keeps_existing_terms(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "vocabulary.json"))
    vocabulary.save_vocabulary(["각막"])
    assert vocabulary.append_vocabulary(["궤양", "각막"]) == ["각막", "궤양"]


# ---- 발음이 붙은 항목: `GitHub(깃허브)` ----

def test_parse_term_reads_pronunciation_in_parentheses():
    assert vocabulary.parse_term("GitHub(깃허브)") == ("GitHub", ["깃허브"])
    assert vocabulary.parse_term("GitHub (깃허브)") == ("GitHub", ["깃허브"])
    assert vocabulary.parse_term("GitHub（깃허브）") == ("GitHub", ["깃허브"])


def test_parse_term_supports_several_pronunciations():
    assert vocabulary.parse_term("GitHub(깃허브, 깃헙)") == ("GitHub", ["깃허브", "깃헙"])
    assert vocabulary.parse_term("GitHub(깃허브/깃헙)") == ("GitHub", ["깃허브", "깃헙"])


def test_parse_term_plain_and_degenerate_entries():
    assert vocabulary.parse_term("각막") == ("각막", [])
    assert vocabulary.parse_term("vet ophthalmology") == ("vet ophthalmology", [])
    assert vocabulary.parse_term("GitHub()") == ("GitHub", [])
    assert vocabulary.parse_term("(깃허브)") == ("(깃허브)", [])  # 앞이 비면 괄호를 발음으로 보지 않는다
    assert vocabulary.parse_term("GitHub(github)") == ("GitHub", [])  # 자기 자신은 발음이 아니다


def test_hint_form_sends_only_the_korean_pronunciation():
    # 영어 표기를 섞어 귀띔하면 모델이 주변 말('컬렉션')까지 영어로 바꾸는 부작용이 있어
    # 모델에는 한글 발음만 알려 준다. 영어로 바꾸는 일은 받아쓴 뒤 소리 매칭이 한다.
    assert vocabulary.hint_form("GitHub(깃허브, 깃헙)") == "깃허브"
    assert vocabulary.hint_form("Qwen(Qn, 큐웬)") == "큐웬"  # 영어 오인식 표기는 귀띔하지 않는다
    assert vocabulary.hint_form("Qwen(Qn)") == "Qwen"  # 한글 발음이 없으면 항목 그대로
    assert vocabulary.hint_form("각막") == "각막"


def test_build_context_sends_pronunciation_as_one_slot():
    assert (
        vocabulary.build_context(["Qdrant(큐드란트)", "각막"])
        == "전문 용어: 큐드란트, 각막"
    )
    # 발음이 붙어도 자리는 항목 하나만 쓴다.
    words = [f"w{i}(발음{i})" for i in range(40)]
    context = vocabulary.build_context(words)
    assert "(" not in context and context.count("발음") == vocabulary.MAX_CONTEXT_TERMS


def test_save_merges_same_term_and_drops_bare_pronunciation(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "vocabulary.json"))
    saved = vocabulary.save_vocabulary(
        ["Qdrant", "큐드란트", "Qdrant(큐드란트)", "GitHub(깃허브)", "GitHub(깃헙)", "각막"]
    )
    # 발음으로 들어간 `큐드란트` 는 따로 남지 않고, 같은 대표 표기는 발음을 모아 하나가 된다.
    assert saved == ["Qdrant(큐드란트)", "GitHub(깃허브, 깃헙)", "각막"]
    assert vocabulary.load_vocabulary() == saved


def test_alias_map_and_surface_forms():
    words = ["GitHub(깃허브, 깃헙)", "각막"]
    assert vocabulary.alias_map(words) == {"GitHub": ["깃허브", "깃헙"]}
    assert vocabulary.canonical_terms(words) == ["GitHub", "각막"]
    assert vocabulary.surface_forms(words) == {"GitHub", "깃허브", "깃헙", "각막"}
