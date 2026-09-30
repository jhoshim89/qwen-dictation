# vocabulary.py
"""받아쓰기 단어 등록(context 바이어싱) 목록을 읽고 쓴다.

목록은 문자열 리스트. 받아쓸 때 이 단어들을 Qwen 에 미리 알려(context)
전문용어·이름을 더 잘 인식하게 한다. (확정 치환이 아니라 인식 편향)
"""
import json
import os
import re
import threading

import app_paths
import secure_store

# 등록 목록은 사람이 관리하는 짧은 용어 모음이다. 대시보드/후보 승인이 잘못된
# 입력을 보내도 디스크와 메모리가 불어나지 않도록 상한을 둔다.
MAX_VOCABULARY_TERMS = 500
MAX_TERM_CHARS = 100

# 항목은 그냥 글자 하나다. 영어 이름이 한글 소리로 적히는 말은 `GitHub(깃허브)` 처럼
# 영어 표기 뒤 괄호에 한글 발음을 붙여 적는다. 저장 형식은 그대로 글자 목록이라 옛 앱과
# 이 목록을 읽는 다른 코드(후보 판정 등)가 깨지지 않는다. 모델에는 한글 발음만 귀띔한다
# (hint_form 참고).
MAX_ALIASES_PER_TERM = 5
MAX_ALIAS_CHARS = 40
_ENTRY_RE = re.compile(r"^(?P<term>.*?)\s*[(（](?P<alias>[^()（）]*)[)）]\s*$")
_ALIAS_SPLIT_RE = re.compile(r"\s*[,，/、·]\s*")
_HANGUL_RE = re.compile(r"[가-힣]")


def parse_term(entry):
    """항목 글자 → (영어 또는 대표 표기, [발음 목록]). 발음이 없으면 목록은 비어 있다.

    `GitHub(깃허브)` → ("GitHub", ["깃허브"]), `GitHub(깃허브, 깃헙)` → 발음 둘.
    괄호 앞뒤 어느 쪽이 비었으면 괄호를 발음 표시로 보지 않고 항목 전체를 그대로 둔다.
    """
    text = str(entry).strip()
    match = _ENTRY_RE.match(text)
    if not match or not match.group("term").strip():
        return text, []
    term = match.group("term").strip()
    aliases = []
    for alias in _ALIAS_SPLIT_RE.split(match.group("alias").strip()):
        alias = alias.strip()
        if (
            alias
            and len(alias) <= MAX_ALIAS_CHARS
            and alias.lower() != term.lower()
            and alias not in aliases
        ):
            aliases.append(alias)
    return term, aliases[:MAX_ALIASES_PER_TERM]


def format_entry(term, aliases):
    return f"{term}({', '.join(aliases)})" if aliases else term


def hint_form(entry):
    """모델에 귀띔하는 글자 — 발음이 있으면 한글 발음 하나(첫 번째), 없으면 항목 그대로.

    영어 표기를 섞어 귀띔하면(`Qdrant(큐드란트)`) 모델이 주변의 등록하지 않은 말까지 영어로
    바꿔 적는 부작용이 있었다('컬렉션'→'Collection', 실제 스트리밍 경로 실측). 그래서 모델에는
    한글 발음만 알려 소리를 정확히 듣게 하고, 영어 표기로 바꾸는 일은 받아쓴 뒤의 소리
    매칭(term_correct)이 맡는다."""
    term, aliases = parse_term(entry)
    for alias in aliases:
        if _HANGUL_RE.search(alias):
            return alias  # 'Qn' 같은 영어 오인식 표기는 귀띔에 쓰지 않는다
    return term


def canonical_terms(words):
    return [parse_term(w)[0] for w in words if str(w).strip()]


def alias_map(words):
    """{대표 표기: [발음, ...]} — 발음이 붙은 항목만."""
    out = {}
    for w in words:
        term, aliases = parse_term(w)
        if aliases:
            out[term] = aliases
    return out


def surface_forms(words):
    """대표 표기와 발음을 모두 펼친 집합 — '이미 등록된 말인가' 판정용."""
    forms = set()
    for w in words:
        term, aliases = parse_term(w)
        if term:
            forms.add(term)
        forms.update(aliases)
    return forms

# load → 수정 → save 순서가 겹치면 한쪽 저장이 통째로 사라진다. 받아쓰기 스레드와
# 대시보드 스레드가 같은 파일을 만지므로 읽고-쓰는 구간을 직렬화한다.
_LOCK = threading.RLock()


def load_vocabulary():
    path = app_paths.vocabulary_path()
    if not os.path.exists(path):
        return []
    try:
        secure_store.ensure_private_file(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(w) for w in data if str(w).strip()]
    except Exception as exc:
        print(f"Vocabulary load error: {exc}")
    return []


def save_vocabulary(words):
    # 같은 대표 표기는 하나로 합치고 발음은 모은다(`GitHub` + `GitHub(깃허브)`).
    merged = {}
    for w in words:
        w = str(w).strip()
        if not w or len(w) > MAX_TERM_CHARS:
            continue
        term, aliases = parse_term(w)
        if not term:
            continue
        known = merged.setdefault(term, [])
        for alias in aliases:
            if alias not in known and len(known) < MAX_ALIASES_PER_TERM:
                known.append(alias)
    # 다른 항목의 발음으로 이미 들어간 낱말(`큐드란트`)이 따로 남아 자리를 차지하지 않게 한다.
    spoken = {alias for aliases in merged.values() for alias in aliases}
    cleaned = []
    for term, aliases in merged.items():
        if not aliases and term in spoken:
            continue
        cleaned.append(format_entry(term, aliases))
        if len(cleaned) >= MAX_VOCABULARY_TERMS:
            break
    try:
        with _LOCK:
            secure_store.atomic_write_json(app_paths.vocabulary_path(), cleaned)
    except Exception as exc:
        print(f"Vocabulary save error: {exc}")
    return cleaned


def append_vocabulary(words):
    """Add terms to the stored list as one atomic read-modify-write."""
    with _LOCK:
        return save_vocabulary(load_vocabulary() + [str(w) for w in words])


def prepend_vocabulary(words):
    """새 단어를 목록 맨 앞에 넣는다.

    모델에 귀띔하는 문맥 단어는 앞에서부터 MAX_CONTEXT_TERMS 개만 쓴다. 사용자가
    지금 자주 고치는 말일수록 모델이 알아야 하므로 자동 등록분은 앞에 둔다.
    (뒤로 밀린 단어도 사후 교정에는 계속 쓰이므로 효력이 사라지지는 않는다.)
    """
    with _LOCK:
        return save_vocabulary([str(w) for w in words] + load_vocabulary())


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
    # 발음이 붙은 항목은 한글 발음 하나로 귀띔한다(자리는 항목 하나).
    terms = [hint_form(w) for w in words if w][:limit]
    labeled_terms = f"{CONTEXT_TERM_LABEL}: " + ", ".join(terms) if terms else ""
    parts = [p for p in (domain, labeled_terms) if p]
    return ". ".join(parts)
