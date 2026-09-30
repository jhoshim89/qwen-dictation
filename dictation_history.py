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
# 사용자가 입력창에서 직접 고친 같은 단어가 이만큼 쌓이면 묻지 않고 등록한다.
# 한 번의 고침으로 결정하지 않기 위한 값 — 두 번은 우연(옆 단어까지 같이 고쳐진 경우
# 등)이 섞이고, 세 번이면 그 사람이 늘 쓰는 말로 봐도 무리가 없다.
AUTO_LEARN_THRESHOLD = 3
# 자동 등록 내역을 이만큼 남긴다(사용자가 나중에 보고 되돌릴 수 있게).
LEARNED_LOG_LIMIT = 50
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
        "learned": data.get("learned", []) if isinstance(data.get("learned", []), list) else [],
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


def record_live_corrections(pairs):
    """입력창에서 직접 고친 (잘못 들은 말, 고친 말) 쌍을 세고, 같은 고침이
    AUTO_LEARN_THRESHOLD 번 쌓이면 묻지 않고 등록한다.

    임계에 못 미친 것은 대시보드의 '추천 단어'에 후보로 남아 직접 등록할 수 있다.
    숨김 처리한 단어와 이미 등록된 단어는 세지 않는다. 이번에 등록된 단어를 돌려준다.
    """
    terms = [str(right).strip() for _wrong, right in (pairs or []) if str(right).strip()]
    if not terms:
        return []
    with _LOCK:
        vocab = vocabulary.surface_forms(vocabulary.load_vocabulary())
        state = _candidate_state()
        dismissed = set(state["dismissed"])
        learned = []
        for term in dict.fromkeys(terms):
            if term in vocab or term in dismissed:
                continue
            count = int(state["counts"].get(term, 0)) + 1
            if count >= AUTO_LEARN_THRESHOLD:
                learned.append(term)
                state["counts"].pop(term, None)
            else:
                state["counts"][term] = count
        if learned:
            now = int(time.time())
            state["learned"] = (
                [{"term": t, "at": now} for t in learned] + state["learned"]
            )[:LEARNED_LOG_LIMIT]
        _save(app_paths.vocabulary_candidates_path(), state)
        if learned:
            vocabulary.prepend_vocabulary(learned)
    return learned


def list_learned():
    """자동 등록된 단어를 최근 것부터 돌려준다(대시보드에 보여 주기 위함)."""
    vocab = vocabulary.surface_forms(vocabulary.load_vocabulary())
    items = []
    for row in _candidate_state()["learned"]:
        term = str((row or {}).get("term", "")).strip()
        if not term:
            continue
        items.append({
            "term": term,
            "at": int((row or {}).get("at", 0) or 0),
            # 사용자가 단어 목록에서 직접 지웠으면 더 이상 쓰이지 않는다는 표시.
            "active": term in vocab,
        })
    return items


def undo_learned(term):
    """자동 등록된 단어를 되돌린다: 목록에서 빼고 다시 등록되지 않게 숨김 처리한다."""
    term = str(term or "").strip()
    if not term:
        raise ValueError("term is required")
    with _LOCK:
        # 발음이 붙은 항목(`GitHub(깃허브)`)도 대표 표기로 알아보고 뺀다.
        vocabulary.save_vocabulary(
            [w for w in vocabulary.load_vocabulary() if vocabulary.parse_term(w)[0] != term]
        )
        state = _candidate_state()
        state["learned"] = [
            row for row in state["learned"]
            if str((row or {}).get("term", "")).strip() != term
        ]
        state["counts"].pop(term, None)
        state["dismissed"] = sorted(set(state["dismissed"]) | {term})
        _save(app_paths.vocabulary_candidates_path(), state)
    return vocabulary.load_vocabulary()


def list_candidates():
    state = _candidate_state()
    vocab = vocabulary.surface_forms(vocabulary.load_vocabulary())
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
