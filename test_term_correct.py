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


def test_fused_particle_term_is_corrected_and_particle_kept():
    # 조사가 붙어 한 어절이 된 오인식도 줄기를 교정하고 조사는 보존한다.
    assert term_correct.correct_terms("각막괴양을 봤다", ["각막궤양"]) == "각막궤양을 봤다"


def test_already_correct_term_with_particle_is_untouched():
    # 이미 올바른 용어에 조사가 붙은 어절은 손대지 않는다(조사 떼먹지 않음).
    assert term_correct.correct_terms("녹내장이 의심된다", ["녹내장"]) == "녹내장이 의심된다"


def test_short_word_sharing_prefix_with_long_term_is_not_expanded():
    # 등록어의 앞부분과 겹치는 짧은 진짜 단어를 등록어로 부풀리지 않는다('각막'→'각막궤양' 금지).
    assert term_correct.correct_terms("각막을 봤다", ["각막궤양"]) == "각막을 봤다"
    assert term_correct.correct_terms("각막이 손상", ["각막궤양"]) == "각막이 손상"


def test_loanword_near_miss_with_ending_is_corrected():
    # '코밋하고'의 줄기 '코밋'을 '커밋'으로 고치고 '하고'는 보존, 이미 맞는 '푸시하자'는 그대로.
    assert term_correct.correct_terms("코밋하고 푸시하자", ["커밋"]) == "커밋하고 푸시하자"


def test_far_mishearing_of_short_word_is_left_alone():
    # 짧은 외래어의 먼 오인식('커미트')은 멀쩡한 말과 구분이 안 돼 일부러 손대지 않는다(문서화된 한계).
    assert term_correct.correct_terms("커미트하고", ["커밋"]) == "커미트하고"


def test_context_bias_safe_when_terms_have_near_spans():
    # 무편향본의 '거미'·'부시해'가 등록어 '커밋'·'푸시'와 음향적으로 가까움 → 안전
    assert term_correct.context_bias_is_safe(
        "거미 타고 부시해", "커밋하고 푸시해", ["커밋", "푸시"]
    ) is True


def test_context_bias_unsafe_when_term_has_no_acoustic_basis():
    # 무편향본에 근거 없는 '커밋'이 편향본에 새로 튀어나옴 → 누출 → 거부
    assert term_correct.context_bias_is_safe(
        "오늘 날씨 좋다", "커밋 오늘 날씨 좋다", ["커밋"]
    ) is False


def test_context_bias_safe_when_no_new_term_introduced():
    # 편향본이 새 등록어를 만들지 않으면(이미 양쪽에 있음) 안전
    assert term_correct.context_bias_is_safe(
        "각막궤양 소견", "각막궤양 소견입니다", ["각막궤양"]
    ) is True


def test_context_bias_unsafe_on_empty_unbiased():
    # 무음/빈 무편향본 위에 등록어가 생기면 근거가 없으므로 거부(고전적 누출 상황)
    assert term_correct.context_bias_is_safe("", "커밋", ["커밋"]) is False
    assert term_correct.context_bias_is_safe("뭐라고", "", ["커밋"]) is False
