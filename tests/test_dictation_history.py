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
