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

# 등록 단어를 그냥 나열하면 Qwen3-ASR 이 그 목록을 '받아쓸 내용'으로 착각해 출력에
# 흘린다(echo/leakage). 머리표로 게이팅하면 모델이 '받아쓸 텍스트'가 아니라 '곧 올
# 오디오에 대한 메타데이터(참고 사전)'로 인식해 새는 걸 막고 인식 정확도도 올라간다.
# (TypeWhisper 실측: 라벨링으로 leakage 사라지고 WER 약 절반 — github #321)
CONTEXT_TERM_LABEL = "전문 용어"


def build_context(words, domain="", limit=MAX_CONTEXT_TERMS):
    """단어 목록 → model.transcribe 의 context 문자열.

    단어 목록은 `전문 용어: a, b, c` 처럼 머리표로 게이팅해 모델이 메타데이터(참고
    사전)로 인식하게 한다 — 그냥 나열하면 출력에 흘리는(echo) 걸 막기 위함이다.
    domain 이 있으면 분야 머리말을 맨 앞 문장으로 두고, 그 뒤에 단어 라벨을 붙인다
    (예: "수의안과 진료. 전문 용어: 각막, 궤양"). 단어는 앞에서부터 limit 개만 쓴다
    — domain 은 그 한도에 포함되지 않는다. 단어가 없으면 라벨도 붙이지 않는다.
    """
    domain = str(domain).strip()
    terms = [w for w in words if w][:limit]
    labeled_terms = f"{CONTEXT_TERM_LABEL}: " + ", ".join(terms) if terms else ""
    parts = [p for p in (domain, labeled_terms) if p]
    return ". ".join(parts)
