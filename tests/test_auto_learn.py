"""받아쓴 뒤 사용자가 직접 고친 것을 배우는 경로 테스트.

핵심은 '무엇을 배우는가'보다 '무엇을 안 배우는가'다 — 잘못 배우면 사전에 엉뚱한 말이
들어가 인식이 오히려 나빠진다.
"""
import importlib

import auto_learn


TYPED = "강막 괴양이 있는 환자는 현관 염색 검사를 먼저 합니다"


def test_learns_sound_alike_correction():
    """소리가 거의 같은 오인식은 배운다."""
    pairs = auto_learn.extract_corrections(
        TYPED, TYPED, "각막 궤양이 있는 환자는 현관 염색 검사를 먼저 합니다"
    )
    assert ("강막 괴양이", "각막 궤양이") in pairs


def test_learns_short_single_word_correction():
    """한 어절만 바뀐 오인식도 배운다(현관→형광 은 유사도가 낮은 편이라 경계 사례)."""
    pairs = auto_learn.extract_corrections(
        TYPED, TYPED, "강막 괴양이 있는 환자는 형광 염색 검사를 먼저 합니다"
    )
    assert ("현관", "형광") in pairs


def test_learns_across_a_spacing_change():
    """띄어쓰기가 붙는 형태의 교정도 배운다."""
    typed = "현관 염색 검사"
    pairs = auto_learn.extract_corrections(typed, typed, "형광염색 검사")
    assert pairs and pairs[0][1] == "형광염색"


def test_ignores_rewrites_near_the_boundary():
    """경계 근처의 '문장 고쳐 쓰기'는 배우지 않는다(유사도 0.60)."""
    typed = "오늘 검사를 했습니다"
    assert auto_learn.extract_corrections(typed, typed, "오늘 환자가 왔습니다") == []


def test_ignores_rewrite_that_is_not_a_mishearing():
    """사용자가 내용을 새로 쓴 것은 오인식이 아니므로 배우지 않는다."""
    pairs = auto_learn.extract_corrections(
        "오늘 진료 본 강아지는 백내장입니다",
        "오늘 진료 본 강아지는 백내장입니다",
        "내일 수술 예약 잡은 고양이는 백내장입니다",
    )
    assert pairs == []


def test_ignores_edits_outside_what_we_typed():
    """우리가 넣지 않은 다른 문단을 고친 것은 우리 일이 아니다."""
    before = "앞 문단은 원래 있던 글입니다.\n" + TYPED
    after = "앞 문단은 원래 잇던 글입니다.\n" + TYPED
    assert auto_learn.extract_corrections(TYPED, before, after) == []


def test_ignores_pure_insertion_and_deletion():
    """새로 쓴 말이나 지운 말은 오인식 근거가 약해 배우지 않는다."""
    assert auto_learn.extract_corrections(TYPED, TYPED, TYPED + " 그리고 추가로 적었습니다") == []
    assert auto_learn.extract_corrections(TYPED, TYPED, "강막 괴양이 있는 환자는") == []


def test_ignores_single_character_and_empty_cases():
    assert auto_learn.extract_corrections("가 나", "가 나", "가 다") == []
    assert auto_learn.extract_corrections(TYPED, TYPED, TYPED) == []
    assert auto_learn.extract_corrections("", "a", "b") == []
    assert auto_learn.extract_corrections(TYPED, "", "") == []


def test_ignores_cross_script_correction():
    """한글↔영어는 소리 비교가 불가능해 배우지 않는다(사후 교정도 못 고침)."""
    assert auto_learn.extract_corrections("큐엔 받아쓰기", "큐엔 받아쓰기", "Qwen 받아쓰기") == []


def test_caps_the_number_learned_from_one_edit():
    typed = "가가가 나나나 다다다 라라라 마마마 바바바 사사사"
    after = "가가가1 나나나1 다다다1 라라라1 마마마1 바바바1 사사사1"
    pairs = auto_learn.extract_corrections(typed, typed, after)
    assert len(pairs) <= auto_learn.MAX_CORRECTIONS_PER_EDIT


def test_ignores_long_sentence_shaped_change():
    """어절이 많이 묶인 덩어리는 용어가 아니라 문장이므로 배우지 않는다."""
    typed = "가나다 라마바 사아자 차카타"
    pairs = auto_learn.extract_corrections(typed, typed, "가나타 라마바1 사아자1 차카타1")
    assert all(len(right.split()) <= auto_learn.MAX_TERM_WORDS for _wrong, right in pairs)


def _history(tmp_path, monkeypatch):
    import app_paths
    import dictation_history
    import vocabulary

    monkeypatch.setattr(app_paths, "user_data_dir", lambda: str(tmp_path))
    importlib.reload(vocabulary)
    importlib.reload(dictation_history)
    monkeypatch.setattr(vocabulary.app_paths, "user_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(dictation_history.app_paths, "user_data_dir", lambda: str(tmp_path))
    return dictation_history, vocabulary


def test_registers_only_after_the_same_fix_repeats(tmp_path, monkeypatch):
    """한 번으로 결정하지 않는다 — 세 번째에 등록된다."""
    history, vocab = _history(tmp_path, monkeypatch)
    pair = [("강막", "각막")]

    assert history.record_live_corrections(pair) == []
    assert "각막" not in vocab.load_vocabulary()
    assert history.record_live_corrections(pair) == []
    assert "각막" not in vocab.load_vocabulary()

    assert history.record_live_corrections(pair) == ["각막"]
    assert "각막" in vocab.load_vocabulary()


def test_learned_term_goes_to_the_front_for_model_hinting(tmp_path, monkeypatch):
    history, vocab = _history(tmp_path, monkeypatch)
    vocab.save_vocabulary(["기존1", "기존2"])
    for _ in range(history.AUTO_LEARN_THRESHOLD):
        learned = history.record_live_corrections([("강막", "각막")])
    assert learned == ["각막"]
    assert vocab.load_vocabulary()[0] == "각막"


def test_below_threshold_stays_visible_as_a_candidate(tmp_path, monkeypatch):
    """임계 전이라도 대시보드 추천 목록에서 직접 등록할 수 있어야 한다."""
    history, _vocab = _history(tmp_path, monkeypatch)
    history.record_live_corrections([("강막", "각막")])
    assert [c["term"] for c in history.list_candidates()] == ["각막"]


def test_does_not_relearn_a_dismissed_term(tmp_path, monkeypatch):
    """사용자가 숨긴 단어는 몇 번을 고쳐도 다시 등록하지 않는다."""
    history, vocab = _history(tmp_path, monkeypatch)
    history.dismiss_candidate("각막")
    for _ in range(history.AUTO_LEARN_THRESHOLD + 2):
        assert history.record_live_corrections([("강막", "각막")]) == []
    assert "각막" not in vocab.load_vocabulary()


def test_does_not_duplicate_an_already_registered_term(tmp_path, monkeypatch):
    history, vocab = _history(tmp_path, monkeypatch)
    vocab.save_vocabulary(["각막"])
    for _ in range(history.AUTO_LEARN_THRESHOLD + 1):
        assert history.record_live_corrections([("강막", "각막")]) == []
    assert vocab.load_vocabulary().count("각막") == 1


def test_same_fix_twice_in_one_edit_counts_once(tmp_path, monkeypatch):
    history, vocab = _history(tmp_path, monkeypatch)
    history.record_live_corrections([("강막", "각막"), ("강막을", "각막")])
    assert "각막" not in vocab.load_vocabulary()


def test_empty_input_is_safe(tmp_path, monkeypatch):
    history, _vocab = _history(tmp_path, monkeypatch)
    assert history.record_live_corrections([]) == []
    assert history.record_live_corrections(None) == []


# --- 전체 흐름: 받아쓰기 → 사용자가 고침 → 세 번째에 등록 → 실제로 인식이 고쳐짐 ---

def _load_wd():
    import importlib.util

    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _recorder(wd, auto_learn_on=True):
    import collections

    rec = wd.Recorder.__new__(wd.Recorder)
    rec.app = type(
        "App",
        (),
        {
            "auto_learn": auto_learn_on,
            "notified": [],
            "notify_learned_terms": lambda self, terms: self.notified.extend(terms),
        },
    )()
    rec.last_typed = ""
    rec._edit_watch = None
    rec.debug_events = collections.deque(maxlen=50)
    rec._debug = lambda reason, **kw: rec.debug_events.append(dict(reason=reason, **kw))
    return rec


def _fake_field(wd, monkeypatch, initial):
    """입력창 읽기를 가짜로 바꾼다(바탕화면을 건드리지 않기 위해)."""
    field = {"value": initial}
    element = object()
    monkeypatch.setattr(
        wd.focus_text, "capture_focused_field", lambda: (element, field["value"])
    )
    monkeypatch.setattr(
        wd.focus_text, "read_field", lambda el: field["value"] if el is element else None
    )
    return field


def test_full_round_trip_registers_on_third_fix_and_fixes_recognition(tmp_path, monkeypatch):
    import term_correct

    wd = _load_wd()
    history, vocab = _history(tmp_path, monkeypatch)
    heard = "강막 궤양 소견입니다"
    fixed = "각막 궤양 소견입니다"
    field = _fake_field(wd, monkeypatch, heard)
    rec = _recorder(wd)

    # 등록 전에는 잘못 들은 말이 그대로 남는다.
    assert term_correct.correct_terms(heard, vocab.load_vocabulary()) == heard

    for round_no in range(1, history.AUTO_LEARN_THRESHOLD + 1):
        field["value"] = heard          # 받아쓰기가 글자를 넣은 직후
        rec.last_typed = heard
        rec._capture_edit_baseline()
        field["value"] = fixed          # 사용자가 입력창에서 직접 고침
        rec._learn_from_previous_edit()  # 다음 받아쓰기 시작 때 읽어 학습
        registered = "각막" in vocab.load_vocabulary()
        assert registered == (round_no == history.AUTO_LEARN_THRESHOLD)

    # 등록된 뒤에는 같은 오인식이 저절로 고쳐진다 — 이게 '학습'의 실제 효과다.
    assert term_correct.correct_terms(heard, vocab.load_vocabulary()) == fixed
    assert rec.app.notified == ["각막"]


def test_round_trip_does_not_log_any_text(tmp_path, monkeypatch):
    """진단 기록에는 개수만 남고 사용자가 고친 글자는 남지 않는다."""
    wd = _load_wd()
    _history(tmp_path, monkeypatch)
    field = _fake_field(wd, monkeypatch, "강막 궤양 소견입니다")
    rec = _recorder(wd)
    rec.last_typed = "강막 궤양 소견입니다"
    rec._capture_edit_baseline()
    field["value"] = "각막 궤양 소견입니다"
    rec._learn_from_previous_edit()

    event = [e for e in rec.debug_events if e["reason"] == "edit_learned"][-1]
    assert set(event) == {"reason", "term_count", "learned_count"}


def test_turning_it_off_never_reads_the_field(tmp_path, monkeypatch):
    wd = _load_wd()
    _history(tmp_path, monkeypatch)
    reads = []
    monkeypatch.setattr(
        wd.focus_text,
        "capture_focused_field",
        lambda: (reads.append("read") or (object(), "무언가")),
    )
    rec = _recorder(wd, auto_learn_on=False)
    rec.last_typed = "강막 궤양"
    rec._capture_edit_baseline()
    assert reads == []
    assert rec._edit_watch is None


def test_field_that_disappears_is_handled(tmp_path, monkeypatch):
    """사용자가 창을 닫았으면 조용히 넘어간다."""
    wd = _load_wd()
    _history(tmp_path, monkeypatch)
    _fake_field(wd, monkeypatch, "강막 궤양")
    monkeypatch.setattr(wd.focus_text, "read_field", lambda el: None)
    rec = _recorder(wd)
    rec.last_typed = "강막 궤양"
    rec._capture_edit_baseline()
    rec._learn_from_previous_edit()
    assert rec._edit_watch is None


# --- 등록된 것을 사용자가 보고 되돌릴 수 있는가 ---

def _learn_once(history, term="각막", wrong="강막"):
    for _ in range(history.AUTO_LEARN_THRESHOLD):
        learned = history.record_live_corrections([(wrong, term)])
    return learned


def test_auto_registered_word_is_listed_for_the_user(tmp_path, monkeypatch):
    history, _vocab = _history(tmp_path, monkeypatch)
    assert history.list_learned() == []

    _learn_once(history)
    rows = history.list_learned()
    assert [r["term"] for r in rows] == ["각막"]
    assert rows[0]["active"] is True
    assert rows[0]["at"] > 0


def test_newest_registration_is_listed_first(tmp_path, monkeypatch):
    history, _vocab = _history(tmp_path, monkeypatch)
    _learn_once(history, "각막", "강막")
    _learn_once(history, "궤양", "괴양")
    assert [r["term"] for r in history.list_learned()] == ["궤양", "각막"]


def test_undo_removes_the_word_and_stops_it_coming_back(tmp_path, monkeypatch):
    history, vocab = _history(tmp_path, monkeypatch)
    _learn_once(history)
    assert "각막" in vocab.load_vocabulary()

    history.undo_learned("각막")
    assert "각막" not in vocab.load_vocabulary()
    assert history.list_learned() == []

    # 되돌린 뒤에는 같은 고침을 아무리 반복해도 다시 등록되지 않는다.
    for _ in range(history.AUTO_LEARN_THRESHOLD + 2):
        assert history.record_live_corrections([("강막", "각막")]) == []
    assert "각막" not in vocab.load_vocabulary()


def test_undo_keeps_other_words(tmp_path, monkeypatch):
    history, vocab = _history(tmp_path, monkeypatch)
    vocab.save_vocabulary(["직접넣은말"])
    _learn_once(history, "각막", "강막")
    _learn_once(history, "궤양", "괴양")

    history.undo_learned("각막")
    remaining = vocab.load_vocabulary()
    assert "직접넣은말" in remaining and "궤양" in remaining and "각막" not in remaining
    assert [r["term"] for r in history.list_learned()] == ["궤양"]


def test_word_deleted_by_hand_shows_as_inactive(tmp_path, monkeypatch):
    """사용자가 단어 목록에서 직접 지우면 '지워짐'으로 보인다(기록은 남는다)."""
    history, vocab = _history(tmp_path, monkeypatch)
    _learn_once(history)
    vocab.save_vocabulary([w for w in vocab.load_vocabulary() if w != "각막"])
    rows = history.list_learned()
    assert rows[0]["term"] == "각막" and rows[0]["active"] is False


def test_undo_rejects_empty_term(tmp_path, monkeypatch):
    import pytest

    history, _vocab = _history(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        history.undo_learned("")


def test_learned_log_is_capped(tmp_path, monkeypatch):
    history, _vocab = _history(tmp_path, monkeypatch)
    for i in range(history.LEARNED_LOG_LIMIT + 5):
        _learn_once(history, f"단어{i}", f"단어{i}x")
    assert len(history.list_learned()) == history.LEARNED_LOG_LIMIT
