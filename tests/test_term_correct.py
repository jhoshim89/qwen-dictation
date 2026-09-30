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


def test_commit_and_push_alias_corrects_korean_loanword_phrase():
    assert (
        term_correct.correct_terms("커밋앤 푸시", ["commit and push"])
        == "커밋 앤 푸시"
    )


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


def test_context_bias_checks_commit_and_push_alias():
    assert term_correct.context_bias_is_safe(
        "오늘 날씨 좋다", "커밋 앤 푸시 오늘 날씨 좋다", ["commit and push"]
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


# ---- 발음이 붙은 항목: 소리가 같으면 대표 표기로 ----

def test_alias_exact_pronunciation_becomes_canonical():
    assert term_correct.correct_terms("코드를 깃허브 저장소에 올렸다", ["GitHub(깃허브)"]) == (
        "코드를 GitHub 저장소에 올렸다"
    )


def test_alias_keeps_particle():
    assert term_correct.correct_terms("깃허브에 올렸다", ["GitHub(깃허브)"]) == "GitHub에 올렸다"
    assert term_correct.correct_terms("큐드란트를 켰다", ["Qdrant(큐드란트)"]) == "Qdrant를 켰다"


def test_alias_that_ends_in_a_particle_shaped_syllable_still_matches():
    # '조테로'의 끝 '로'는 조사 모양이다. 통째로도, 조사가 붙어도 맞아야 한다.
    entries = ["Zotero(조테로)"]
    assert term_correct.correct_terms("조테로 라이브러리", entries) == "Zotero 라이브러리"
    assert term_correct.correct_terms("조테로에 정리했다", entries) == "Zotero에 정리했다"
    assert term_correct.correct_terms("조태로 라이브러리", entries) == "Zotero 라이브러리"


def test_alias_near_miss_pronunciation_is_matched_by_sound():
    assert term_correct.correct_terms("옥시디언 노트", ["Obsidian(옵시디언)"]) == "Obsidian 노트"


def test_alias_uses_any_of_several_pronunciations():
    entries = ["GitHub(깃허브, 깃헙)"]
    assert term_correct.correct_terms("깃헙에 올림", entries) == "GitHub에 올림"


def test_alias_does_not_touch_look_alike_real_words():
    entries = ["Claude(클로드)", "Qdrant(큐드란트)", "Python(파이썬)", "PubMed(퍼브메드)"]
    for sentence in [
        "클라우드 서버에 백업했다",
        "클로버 잎을 봤다",
        "큐브 모양 조각",
        "파이 모양 그래프",
        "퍼블릭 도메인 이미지",
    ]:
        assert term_correct.correct_terms(sentence, entries) == sentence


def test_alias_registered_term_is_never_rewritten_by_alias():
    # 등록된 원어(`커밋`)는 다른 항목의 발음 규칙보다 앞선다.
    entries = ["커밋", "commit(커밋)"]
    assert term_correct.correct_terms("커밋했다", entries) == "커밋했다"


def test_plain_entries_behave_as_before_when_mixed_with_alias_entries():
    entries = ["각막궤양", "GitHub(깃허브)"]
    assert term_correct.correct_terms("각막계양 소견, 깃허브", entries) == "각막궤양 소견, GitHub"


def test_multiword_pronunciation_is_replaced():
    assert term_correct.correct_terms("챗 지피티 답변", ["ChatGPT(챗 지피티)"]) == "ChatGPT 답변"


def test_context_bias_guard_accepts_pronunciation_as_evidence():
    # 편향본이 Qdrant 를 냈고, 무편향본에는 한글 발음(큐드란) 근처 소리가 있다 → 근거 있음.
    entries = ["Qdrant(큐드란트)"]
    assert term_correct.context_bias_is_safe("큐드란 컬렉션", "Qdrant 컬렉션", entries)
    # 소리 근거가 전혀 없는 등록어는 여전히 거부한다.
    assert not term_correct.context_bias_is_safe("오늘 날씨 좋다", "Qdrant 날씨 좋다", entries)


def test_pronunciation_split_by_spaces_is_still_matched():
    # ASR 이 붙여 쓰는 말을 띄어 쓰는 경우('오픈 알렉스'), 조사가 붙은 경우까지.
    entries = ["OpenAlex(오픈알렉스)"]
    assert term_correct.correct_terms("오픈 알렉스에서 가져왔다", entries) == "OpenAlex에서 가져왔다"
    assert term_correct.correct_terms("오픈알렉스 저자", entries) == "OpenAlex 저자"


def test_split_words_are_not_joined_across_punctuation():
    entries = ["OpenAlex(오픈알렉스)"]
    assert term_correct.correct_terms("오픈, 알렉스", entries) == "오픈, 알렉스"


def test_alias_can_be_an_english_misrecognition_and_ignores_case():
    # 모델이 '큐웬'을 'Qn' 으로 적는 경우 — 그 표기를 발음 목록에 넣어 두면 잡는다.
    entries = ["Qwen(큐웬, Qn)"]
    assert term_correct.correct_terms("QN 모델로 돌렸다", entries) == "Qwen 모델로 돌렸다"
    assert term_correct.correct_terms("큐웬 모델", entries) == "Qwen 모델"


def test_mixed_script_pronunciation_matches_exactly():
    entries = ["ChatGPT(챗지피티, 챗GPT, 챗 GPT)"]
    assert term_correct.correct_terms("챗GPT가 만들었다", entries) == "ChatGPT가 만들었다"
    assert term_correct.correct_terms("챗 GPT가 만들었다", entries) == "ChatGPT가 만들었다"


def test_context_bias_guard_still_rejects_when_pronunciation_is_absent_from_unbiased():
    entries = ["Qdrant(큐드란트)", "GitHub(깃허브)"]
    # Qdrant 는 무편향본의 소리(큐드란)에서 비롯됐지만, GitHub 는 근거가 없다.
    assert not term_correct.context_bias_is_safe(
        "큐드란 컬렉션", "Qdrant GitHub 컬렉션", entries
    )


def test_particle_is_kept_even_when_the_whole_word_is_also_close():
    # '챗지피티가' 는 통째로도 발음('챗지피티')과 닮았지만 줄기가 정확히 맞으므로 조사를 살린다.
    entries = ["ChatGPT(챗지피티)"]
    assert term_correct.correct_terms("챗지피티가 만든 글", entries) == "ChatGPT가 만든 글"
    assert term_correct.correct_terms("챗지피티를 썼다", entries) == "ChatGPT를 썼다"
