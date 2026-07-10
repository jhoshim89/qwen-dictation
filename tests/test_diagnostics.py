import json

import app_paths
import diagnostics


def test_diagnostics_persists_only_operational_fields(tmp_path, monkeypatch):
    path = tmp_path / "diagnostics.jsonl"
    monkeypatch.setattr(app_paths, "diagnostics_path", lambda: str(path))

    diagnostics.record_event({
        "reason": "typed",
        "old_len": 0,
        "new_len": 8,
        "text": "저장되면 안 되는 받아쓰기",
        "hypo": "저장되면 안 되는 가설",
        "audio": b"not-audio",
    })

    raw = path.read_text(encoding="utf-8")
    saved = json.loads(raw)
    assert saved["reason"] == "typed"
    assert saved["new_len"] == 8
    assert "text" not in raw
    assert "hypo" not in raw
    assert "audio" not in raw


def test_diagnostics_load_skips_broken_lines_and_limits_results(tmp_path, monkeypatch):
    path = tmp_path / "diagnostics.jsonl"
    monkeypatch.setattr(app_paths, "diagnostics_path", lambda: str(path))
    path.write_text(
        '{"reason":"one"}\nnot-json\n{"reason":"two"}\n',
        encoding="utf-8",
    )

    assert [event["reason"] for event in diagnostics.load_events(limit=1)] == ["two"]
