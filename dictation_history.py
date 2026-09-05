"""Local-only transcript history and user-approved vocabulary suggestions."""
import difflib
import json
import os
import re
import threading
import time
import uuid

import app_paths
import secure_store
import vocabulary

HISTORY_LIMIT = 50
SUGGESTION_THRESHOLD = 2
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣._+-]*")

# 받아쓰기 스레드(add_history)와 대시보드 스레드(정정/후보 승인)가 같은 파일에
# load → 수정 → save 를 하므로, 겹치면 한쪽 기록이 사라진다. 그 구간을 직렬화한다.
_LOCK = threading.RLock()


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        secure_store.ensure_private_file(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as exc:
        print(f"History load error ({path}): {exc}")
        return default


def _save(path, data):
    secure_store.atomic_write_json(path, data)


def load_history():
    data = _load(app_paths.history_path(), [])
    return data if isinstance(data, list) else []


def add_history(text):
    text = str(text or "").strip()
    if not text:
        return None
    entries = load_history()
    entry = {"id": uuid.uuid4().hex, "text": text, "created_at": int(time.time())}
    with _LOCK:
        _save(app_paths.history_path(), ([entry] + load_history())[:HISTORY_LIMIT])
    return entry


def clear_history():
    with _LOCK:
        _save(app_paths.history_path(), [])


def _candidate_state():
    data = _load(app_paths.vocabulary_candidates_path(), {})
    if not isinstance(data, dict):
        data = {}
    return {
        "counts": data.get("counts", {}) if isinstance(data.get("counts", {}), dict) else {},
        "dismissed": data.get("dismissed", []) if isinstance(data.get("dismissed", []), list) else [],
        "submissions": data.get("submissions", {}) if isinstance(data.get("submissions", {}), dict) else {},
    }


def _candidate_terms(original, corrected):
    before = _TOKEN_RE.findall(str(original or ""))
    after = _TOKEN_RE.findall(str(corrected or ""))
    matcher = difflib.SequenceMatcher(a=before, b=after)
    terms = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            value = " ".join(after[j1:j2]).strip()
            if len(value) >= 2:
                terms.append(value)
    return list(dict.fromkeys(terms))


def record_correction(history_id, corrected_text):
    entry = next((item for item in load_history() if item.get("id") == history_id), None)
    if entry is None:
        raise ValueError("history entry not found")
    terms = _candidate_terms(entry.get("text", ""), corrected_text)
    with _LOCK:
        state = _candidate_state()
        previous = set(state["submissions"].get(history_id, []))
        for term in terms:
            if term not in previous:
                state["counts"][term] = int(state["counts"].get(term, 0)) + 1
        state["submissions"][history_id] = sorted(previous | set(terms))
        _prune_submissions(state)
        _save(app_paths.vocabulary_candidates_path(), state)
    return terms


def _prune_submissions(state):
    """Drop submission records for history entries that have rotated out."""
    live_ids = {item.get("id") for item in load_history()}
    state["submissions"] = {
        key: value for key, value in state["submissions"].items() if key in live_ids
    }


def list_candidates():
    state = _candidate_state()
    vocab = set(vocabulary.load_vocabulary())
    dismissed = set(state["dismissed"])
    return sorted(
        [
            {"term": term, "count": int(count), "recommended": int(count) >= SUGGESTION_THRESHOLD}
            for term, count in state["counts"].items()
            if term not in vocab and term not in dismissed
        ],
        key=lambda item: (-item["recommended"], -item["count"], item["term"]),
    )


def accept_candidate(term):
    term = str(term or "").strip()
    if not term:
        raise ValueError("term is required")
    return vocabulary.append_vocabulary([term])


def dismiss_candidate(term):
    term = str(term or "").strip()
    if not term:
        raise ValueError("term is required")
    with _LOCK:
        state = _candidate_state()
        state["dismissed"] = sorted(set(state["dismissed"]) | {term})
        _save(app_paths.vocabulary_candidates_path(), state)


def reset_dismissed():
    with _LOCK:
        state = _candidate_state()
        state["dismissed"] = []
        _save(app_paths.vocabulary_candidates_path(), state)
