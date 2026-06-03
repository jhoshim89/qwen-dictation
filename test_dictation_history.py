import app_paths
import dictation_history
import vocabulary


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
