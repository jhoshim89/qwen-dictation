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


# 문맥 단어가 많으면 받아쓰기가 느려지고, 약한 소리에 목록이 통째로 새는 echo 위험이
# 커진다. Deepgram 등은 "가장 중요한 20~50개만"을 권장한다 — 그 하단으로 제한한다.
MAX_CONTEXT_TERMS = 24


def build_context(words, domain="", limit=MAX_CONTEXT_TERMS):
    """단어 목록 → model.transcribe 의 context 문자열.

    domain 이 있으면 분야 머리말로 맨 앞에 붙여 모델을 그 분야로 편향한다(예:
    "수의안과 진료"). 단어는 앞에서부터 limit 개만 쓴다 — domain 은 그 한도에
    포함되지 않는다. domain 이 비면 기존과 동일하게 단어 목록만 반환한다.
    """
    domain = str(domain).strip()
    terms = [w for w in words if w]
    parts = ([domain] if domain else []) + terms[:limit]
    return ", ".join(parts)
