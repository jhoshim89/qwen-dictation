import app_paths
import dictation_history
import vocabulary
import os
import stat


def _paths(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "history_path", lambda: str(tmp_path / "history.json"))
    monkeypatch.setattr(app_paths, "vocabulary_candidates_path", lambda: str(tmp_path / "candidates.json"))
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "vocabulary.json"))


def test_history_keeps_latest_50_non_empty_entries(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    assert dictation_history.add_history(" ") is None
    for index in range(55):
        dictation_history.add_history(f"text {index}")
    history = dictation_history.load_history()
    assert len(history) == 50
    assert history[0]["text"] == "text 54"


def test_correction_candidate_counts_once_per_history_and_accepts(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    first = dictation_history.add_history("큐엔 테스트")
    second = dictation_history.add_history("큐엔 문서")
    assert dictation_history.record_correction(first["id"], "Qwen 테스트") == ["Qwen"]
    dictation_history.record_correction(first["id"], "Qwen 테스트")
    assert dictation_history.list_candidates()[0]["count"] == 1
    dictation_history.record_correction(second["id"], "Qwen 문서")
    assert dictation_history.list_candidates()[0] == {"term": "Qwen", "count": 2, "recommended": True}
    dictation_history.accept_candidate("Qwen")
    assert vocabulary.load_vocabulary() == ["Qwen"]
    assert dictation_history.list_candidates() == []


def test_dismiss_and_reset_candidate(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    item = dictation_history.add_history("큐엔")
    dictation_history.record_correction(item["id"], "Qwen")
    dictation_history.dismiss_candidate("Qwen")
    assert dictation_history.list_candidates() == []
    dictation_history.reset_dismissed()
    assert dictation_history.list_candidates()[0]["term"] == "Qwen"


def test_history_clear_and_private_permissions(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    dictation_history.add_history("private text")
    path = tmp_path / "history.json"

    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    dictation_history.clear_history()
    assert dictation_history.load_history() == []


def test_submissions_pruned_when_history_rotates(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    first = dictation_history.add_history("큐엔 테스트")
    dictation_history.record_correction(first["id"], "Qwen 테스트")
    for index in range(dictation_history.HISTORY_LIMIT):
        dictation_history.add_history(f"filler {index}")
    latest = dictation_history.load_history()[0]
    dictation_history.record_correction(latest["id"], "filler 마지막")
    state = dictation_history._candidate_state()
    assert first["id"] not in state["submissions"]
    assert latest["id"] in state["submissions"]
    # 후보 카운트 자체는 유지된다 — 정리 대상은 history 별 제출 기록뿐이다.
    assert any(item["term"] == "Qwen" for item in dictation_history.list_candidates())


def test_pronunciation_entry_counts_as_registered_for_candidates(tmp_path, monkeypatch):
    # `GitHub(깃허브)` 로 합쳐 둔 뒤에는 대표 표기도 발음도 다시 후보나 자동 등록으로 나오지 않는다.
    _paths(tmp_path, monkeypatch)
    vocabulary.save_vocabulary(["GitHub(깃허브)"])
    for _ in range(dictation_history.AUTO_LEARN_THRESHOLD):
        assert dictation_history.record_live_corrections([("기트허브", "깃허브")]) == []
        assert dictation_history.record_live_corrections([("깃 허브", "GitHub")]) == []
    assert dictation_history.list_candidates() == []
    assert vocabulary.load_vocabulary() == ["GitHub(깃허브)"]


def test_undo_learned_removes_entry_carrying_a_pronunciation(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    vocabulary.save_vocabulary(["GitHub(깃허브)", "각막"])
    assert dictation_history.undo_learned("GitHub") == ["각막"]


def test_hangul_to_english_correction_learns_pronunciation_after_three(tmp_path, monkeypatch):
    # 기타부→GitHub 를 세 번 고치면 GitHub 항목에 '기타부' 발음이 붙는다(첫 발음 순서는 그대로).
    _paths(tmp_path, monkeypatch)
    vocabulary.save_vocabulary(["GitHub(깃허브)", "각막"])
    pair = [("기타부", "GitHub")]
    assert dictation_history.record_live_corrections(pair) == []
    assert dictation_history.record_live_corrections(pair) == []
    assert dictation_history.list_candidates()[0]["term"] == "GitHub(기타부)"
    assert dictation_history.record_live_corrections(pair) == ["GitHub(기타부)"]
    assert vocabulary.load_vocabulary() == ["GitHub(깃허브, 기타부)", "각막"]
    assert dictation_history.list_candidates() == []
    assert dictation_history.list_learned()[0] == {
        "term": "GitHub(기타부)", "at": dictation_history.list_learned()[0]["at"], "active": True,
    }
    # 이미 붙은 발음은 다시 세지 않는다.
    assert dictation_history.record_live_corrections(pair) == []


def test_hangul_to_english_learning_creates_entry_and_undo_removes_only_it(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    vocabulary.save_vocabulary(["각막"])
    for _ in range(dictation_history.AUTO_LEARN_THRESHOLD):
        learned = dictation_history.record_live_corrections([("가디스트", "GADIST")])
    assert learned == ["GADIST(가디스트)"]
    assert vocabulary.load_vocabulary() == ["GADIST(가디스트)", "각막"]
    assert dictation_history.undo_learned("GADIST(가디스트)") == ["각막"]
    # 되돌린 뒤에는 같은 고침을 다시 세지 않는다.
    for _ in range(dictation_history.AUTO_LEARN_THRESHOLD):
        assert dictation_history.record_live_corrections([("가디스트", "GADIST")]) == []


def test_undo_learned_pronunciation_keeps_user_typed_pronunciation(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    vocabulary.save_vocabulary(["GitHub(깃허브)"])
    for _ in range(dictation_history.AUTO_LEARN_THRESHOLD):
        dictation_history.record_live_corrections([("기타부", "GitHub")])
    assert dictation_history.undo_learned("GitHub(기타부)") == ["GitHub(깃허브)"]
