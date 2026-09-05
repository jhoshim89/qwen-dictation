"""Privacy-safe persistent runtime diagnostics.

Only operational metadata is accepted. Transcript text and audio are never
written, and unknown fields are dropped rather than persisted accidentally.
"""
import json
import os
import threading
import time

import app_paths
import secure_store


MAX_EVENTS = 200
ROTATE_BYTES = 128 * 1024
_LOCK = threading.Lock()
_ALLOWED_FIELDS = {
    "ts",
    "reason",
    "phase",
    "error",
    "engine",
    "min_volume",
    "input_device",
    "resolved_device",
    "device_index",
    "preroll_frames",
    "frame_count",
    "window_start",
    "frames",
    "peak",
    "gate",
    "window_ms",
    "finalizing",
    "text_len",
    "old_len",
    "new_len",
    "append_only",
    "session_id",
    "retry_count",
    "age_ms",
    "capture_ready",
}


def _safe_event(event):
    safe = {}
    for key, value in dict(event or {}).items():
        if key not in _ALLOWED_FIELDS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value[:1000] if isinstance(value, str) else value
    safe.setdefault("ts", round(time.time(), 3))
    safe.setdefault("reason", "unknown")
    return safe


def _load_unlocked(limit):
    path = app_paths.diagnostics_path()
    if not os.path.exists(path):
        return []
    events = []
    try:
        secure_store.ensure_private_file(path)
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    events.append(_safe_event(value))
    except OSError:
        return []
    return events[-max(0, int(limit)):]


def load_events(limit=MAX_EVENTS):
    with _LOCK:
        return _load_unlocked(limit)


def record_event(event):
    payload = _safe_event(event)
    path = app_paths.diagnostics_path()
    with _LOCK:
        try:
            secure_store.append_private_text(
                path, json.dumps(payload, ensure_ascii=False) + "\n"
            )
            if os.path.getsize(path) <= ROTATE_BYTES:
                return
            recent = _load_unlocked(MAX_EVENTS)
            content = "".join(
                json.dumps(item, ensure_ascii=False) + "\n" for item in recent
            )
            secure_store.atomic_write_text(path, content)
        except OSError:
            # Diagnostics must never break dictation.
            return
