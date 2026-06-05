import term_correct


def test_exact_term_is_unchanged():
    assert term_correct.correct_terms("녹내장 환자 봤어", ["녹내장"]) == "녹내장 환자 봤어"


def test_korean_near_miss_replaced_at_jamo_level():
    # 한 음절의 모음만 다른 오인식(계양↔궤양) → 같은 소리로 보고 교정
    assert term_correct.correct_terms("각막계양 소견입니다", ["각막궤양"]) == "각막궤양 소견입니다"


def test_below_threshold_is_left_alone():
    # 전혀 다른 말은 건드리지 않는다(멀쩡한 말 오교체 방지)
    assert term_correct.correct_terms("안녕하세요 반갑습니다", ["각막궤양"]) == "안녕하세요 반갑습니다"


def test_multiword_latin_term_near_miss_replaced():
    assert term_correct.correct_terms(
        "the corneal ulcar healed well", ["corneal ulcer"]
    ) == "the corneal ulcer healed well"


def test_latin_term_case_is_normalized():
    assert term_correct.correct_terms("qwen 좋아", ["Qwen"]) == "Qwen 좋아"


def test_short_term_is_not_fuzzy_matched():
    # 1음절급 짧은 용어는 우연한 0.8 매칭을 막으려 fuzzy 건너뜀(정확히 같을 때만 유지)
    assert term_correct.correct_terms("문을 닫아", ["눈"]) == "문을 닫아"


def test_empty_inputs_are_safe():
    assert term_correct.correct_terms("", ["녹내장"]) == ""
    assert term_correct.correct_terms("녹내장", []) == "녹내장"


def test_cross_script_is_a_known_limitation():
    # 영어 용어가 한글로 들린 경우(큐엔↔Qwen)는 글자체가 달라 교정 못 함(문서화된 한계)
    assert term_correct.correct_terms("큐엔 좋아", ["Qwen"]) == "큐엔 좋아"
