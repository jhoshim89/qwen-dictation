"""Local-only transcript history and user-approved vocabulary suggestions."""
import difflib
import json
import os
import re
import time
import uuid

import app_paths
import vocabulary

HISTORY_LIMIT = 50
SUGGESTION_THRESHOLD = 2
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣._+-]*")


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as exc:
        print(f"History load error ({path}): {exc}")
        return default


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_history():
    data = _load(app_paths.history_path(), [])
    return data if isinstance(data, list) else []


def add_history(text):
    text = str(text or "").strip()
    if not text:
        return None
    entries = load_history()
    entry = {"id": uuid.uuid4().hex, "text": text, "created_at": int(time.time())}
    _save(app_paths.history_path(), ([entry] + entries)[:HISTORY_LIMIT])
    return entry


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
    state = _candidate_state()
    previous = set(state["submissions"].get(history_id, []))
    for term in terms:
        if term not in previous:
            state["counts"][term] = int(state["counts"].get(term, 0)) + 1
    state["submissions"][history_id] = sorted(previous | set(terms))
    _save(app_paths.vocabulary_candidates_path(), state)
    return terms


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
    return vocabulary.save_vocabulary(vocabulary.load_vocabulary() + [term])


def dismiss_candidate(term):
    term = str(term or "").strip()
    if not term:
        raise ValueError("term is required")
    state = _candidate_state()
    state["dismissed"] = sorted(set(state["dismissed"]) | {term})
    _save(app_paths.vocabulary_candidates_path(), state)


def reset_dismissed():
    state = _candidate_state()
    state["dismissed"] = []
    _save(app_paths.vocabulary_candidates_path(), state)
