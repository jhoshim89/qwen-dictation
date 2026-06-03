# vocabulary.py
"""받아쓰기 단어 등록(context 바이어싱) 목록을 읽고 쓴다.

목록은 문자열 리스트. 받아쓸 때 이 단어들을 Qwen 에 미리 알려(context)
전문용어·이름을 더 잘 인식하게 한다. (확정 치환이 아니라 인식 편향)
"""
import json
import os

import app_paths


def load_vocabulary():
    path = app_paths.vocabulary_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(w) for w in data if str(w).strip()]
    except Exception as exc:
        print(f"Vocabulary load error: {exc}")
    return []


def save_vocabulary(words):
    seen = set()
    cleaned = []
    for w in words:
        w = str(w).strip()
        if w and w not in seen:
            seen.add(w)
            cleaned.append(w)
    try:
        with open(app_paths.vocabulary_path(), "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"Vocabulary save error: {exc}")
    return cleaned


def build_context(words):
    """단어 목록 → model.transcribe 의 context 문자열."""
    return ", ".join(w for w in words if w)
