"""받아쓴 텍스트를 등록 용어로 사후 교정한다.

모델에는 용어 목록을 주지 않으므로(누출 0) 인식은 순수 음향으로만 이뤄지고, 여기서
'소리가 거의 같은' 토막만 등록 용어로 바꾼다. 한국어는 NFD 로 음절을 자모로 분해해
소리 단위로 비교한다(계양↔궤양). 같은 글자체 근접 오인식이 대상이며, 교차 글자체
(영어↔한글)는 비교가 불가능해 그냥은 손대지 않는다(한계). 다만 항목에 한글 발음을 붙이면
(`GitHub(깃허브)`) 그 발음과 소리가 같은 말을 영어 표기로 바꾼다 — 사용자가 적은 발음에
한해서만 바꾸는 소리 기반 매칭이지, 무조건 치환 사전이 아니다.

한 단어 용어는 어절마다 조사/어미를 떼고 '줄기'만 비교한다 — '커밋하고'처럼 뒤에 말이
붙어 한 덩어리가 돼도 줄기('커밋')를 교정하고 조사('하고')는 그대로 둔다. 길이 가드로
등록어의 앞부분과 겹치는 짧은 진짜 단어를 부풀리는 것(각막→각막궤양)을 막는다.
"""
import re
import unicodedata
from difflib import SequenceMatcher

import vocabulary

# "남들 하는 만큼": 유사도가 이 값 이상일 때만 교체한다(멀쩡한 말 오교체 방지).
SIMILARITY_THRESHOLD = 0.8
# 자모로 분해했을 때 이보다 짧은 용어는 fuzzy 매칭하지 않는다(짧으면 우연 매칭 위험).
MIN_NORM_LEN = 4
# 비교 대상과 용어의 자모 길이비가 이 값 미만이면 교체하지 않는다 — 긴 등록어의 앞부분과
# 겹치는 짧은 진짜 단어를 등록어로 부풀리는 것('각막'→'각막궤양')을 막는다.
LEN_RATIO_MIN = 0.8
# 편향(context) 결과가 무편향 결과와 '음향적으로 이어지는지' 판단할 때 쓰는 근접 임계.
# SIMILARITY_THRESHOLD(교체용 0.8)보다 낮다 — 모델은 오디오+힌트로 '거미→커밋'(0.67)처럼
# 순수 텍스트 fuzzy 가 못 잇는 간극을 메우므로, 가드는 '근거가 아예 없는' 경우만 막는다.
BIAS_NEAR_THRESHOLD = 0.55

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_TERM_ALIASES = {
    "commit and push": ("커밋 앤 푸시", "커밋", "푸시"),
}

# 명사 뒤에 붙는 흔한 조사 + '하다' 활용 어미. 긴 것부터 떼어 본다. 등록 용어는 명사이므로
# 이 목록이 실사용의 어절 융합('커밋하고','각막궤양을')을 거의 덮는다.
_ENDINGS = sorted(
    [
        "하고", "하자", "하는", "하면", "하니까", "해서", "해도", "했다", "했어", "했고",
        "합니다", "했습니다", "한다", "하지", "하기", "해야", "하든", "한", "할", "함", "해", "했",
        "이라는", "라는", "이라", "으로", "에서", "한테", "처럼", "부터", "까지", "마다", "밖에",
        "이", "가", "을", "를", "은", "는", "에", "로", "도", "만", "와", "과", "의",
    ],
    key=len,
    reverse=True,
)


def _norm(text):
    # NFD: 한글 음절 → 자모(초/중/종성)로 분해. 소리 단위 비교가 되고, 라틴 문자는
    # 소문자화로 대소문자 차이를 흡수한다.
    return unicodedata.normalize("NFD", text).lower()


def _similarity(a, b):
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _len_ratio(a, b):
    la, lb = len(_norm(a)), len(_norm(b))
    hi = max(la, lb)
    return min(la, lb) / hi if hi else 0.0


def _strip_ending(word):
    """어절에서 끝의 조사/어미 하나를 떼어 (줄기, 어미) 로 돌려준다. 떼고 남는 줄기가
    2글자 미만이면 떼지 않는다(과도한 분리 방지)."""
    for end in _ENDINGS:
        if len(word) - len(end) >= 2 and word.endswith(end):
            return word[: -len(end)], end
    return word, ""


def _expand_terms(terms):
    out = []
    seen = set()
    for term in terms:
        term = term.strip()
        for candidate in (term, *_TERM_ALIASES.get(term.lower(), ())):
            if candidate and candidate not in seen:
                seen.add(candidate)
                out.append(candidate)
    return out


def _replace_spans(text, term, n, threshold):
    """text 안에서 n개 단어로 된 토막이 term 과 임계 이상 비슷하면 term 으로 바꾼다."""
    matches = list(_WORD_RE.finditer(text))
    min_size = max(1, n - 1)
    max_size = min(len(matches), n)
    if max_size < min_size:
        return text
    out = []
    last = 0
    i = 0
    while i < len(matches):
        replaced = False
        for size in range(max_size, min_size - 1, -1):
            if i + size > len(matches):
                continue
            span_start = matches[i].start()
            span_end = matches[i + size - 1].end()
            span = text[span_start:span_end]
            if span != term and _similarity(span, term) >= threshold:
                out.append(text[last:span_start])
                out.append(term)
                last = span_end
                i += size
                replaced = True
                break
        if not replaced:
            i += 1
    out.append(text[last:])
    return "".join(out)


def _correct_single_terms(text, terms, threshold):
    """한 단어 용어들을 어절 단위로 교정한다. 어절에서 조사를 떼고 줄기를 용어와 비교해
    근접하면 줄기만 용어로 바꾸고 조사는 보존한다. 이미 올바른 어절은 손대지 않는다."""
    out = []
    for tok in re.findall(r"\w+|\W+", text, re.UNICODE):
        if not _WORD_RE.match(tok):
            out.append(tok)
            continue
        stem, ending = _strip_ending(tok)
        cand = stem if ending else tok
        replaced = None
        for term in terms:
            if cand == term:
                break  # 이미 올바름 → 손대지 않음(조사 보존)
            if _len_ratio(cand, term) >= LEN_RATIO_MIN and _similarity(cand, term) >= threshold:
                replaced = term + ending
                break
        out.append(replaced if replaced is not None else tok)
    return "".join(out)


def _alias_score(candidate, alias, threshold):
    """candidate 가 alias(사용자가 적어 둔 발음)와 얼마나 같은 소리인지. 못 미치면 0.

    띄어쓰기는 ASR 마다 흔들려서(오픈알렉스↔오픈 알렉스) 공백을 뺀 소리로 견준다."""
    alias = "".join(alias.split())
    candidate = "".join(candidate.split())
    if _norm(candidate) == _norm(alias):
        return 2.0  # 대소문자만 다른 것('QN'↔'Qn')도 같은 발음으로 본다
    if len(_norm(alias)) < MIN_NORM_LEN:
        return 0.0  # 짧은 발음은 우연 일치가 많아 정확히 같을 때만 인정
    if _len_ratio(candidate, alias) < LEN_RATIO_MIN:
        return 0.0
    score = _similarity(candidate, alias)
    return score if score >= threshold else 0.0


def _apply_aliases(text, pairs, protected, threshold):
    """발음(소리) → 대표 표기. 발음과 소리가 같거나 임계 이상 비슷할 때만 바꾼다. 조사는 그대로 둔다.

    통째 어절과, 조사를 뗀 줄기를 둘 다 견주어 더 잘 맞는 쪽을 쓴다 — '조테로'처럼 발음 끝
    글자가 조사 모양('로')이어도 통째 견주면 맞고, '조테로에'는 줄기('조테로')로 맞는다.
    붙여 쓰는 말이 띄어 쓰여 나온 경우('오픈 알렉스')를 위해 이어진 어절 3개까지(띄어 쓴
    발음이면 그 어절 수보다 둘 더까지) 붙여서 견준다, 긴 것부터. 사이가 공백뿐일 때만 잇고
    구두점은 넘어가지 않는다."""
    max_size = min(5, max(3, max(len(alias.split()) for alias, _ in pairs) + 2))
    toks = re.findall(r"\w+|\W+", text, re.UNICODE)
    out = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        if not _WORD_RE.match(tok):
            out.append(tok)
            i += 1
            continue
        replaced = None
        consumed = 1
        for size in range(max_size, 0, -1):
            words = [tok]
            for k in range(1, size):
                sep = toks[i + 2 * k - 1] if i + 2 * k - 1 < len(toks) else ""
                word = toks[i + 2 * k] if i + 2 * k < len(toks) else ""
                if not sep or not sep.isspace() or not _WORD_RE.match(word):
                    words = None
                    break
                words.append(word)
            if words is None:
                continue
            joined = "".join(words)
            stem, ending = _strip_ending(joined)
            if any(w in protected for w in words) or (ending and stem in protected):
                continue  # 등록된 원어(조사가 붙은 것 포함)는 발음 규칙보다 앞선다
            # 통째와 조사를 뗀 줄기를 둘 다 견주어 더 잘 맞는 쪽을 쓴다 — '챗지피티가'는 통째로도
            # 웬만큼 닮았지만 줄기('챗지피티')가 정확히 맞으므로 조사를 살려야 한다.
            best = (0.0, None)
            for cand, tail in [(joined, "")] + ([(stem, ending)] if ending else []):
                for alias, term in pairs:
                    score = _alias_score(cand, alias, threshold)
                    if score > best[0]:
                        best = (score, term + tail)
            if best[1] is not None:
                replaced, consumed = best[1], 2 * size - 1
                break
        if replaced is not None:
            out.append(replaced)
            i += consumed
        else:
            out.append(tok)
            i += 1
    return "".join(out)


def _has_near_span(text, term, threshold):
    """text 안에 term 과 threshold 이상으로 닮은 토막(term 단어수 또는 +1)이 하나라도
    있으면 True. 등록어가 무편향본의 어떤 소리 토막에서 비롯됐는지 확인하는 용도."""
    words = list(_WORD_RE.finditer(text))
    n = max(1, len(term.split()))
    for size in (n, n + 1):
        if len(words) < size:
            continue
        for i in range(len(words) - size + 1):
            span = text[words[i].start(): words[i + size - 1].end()]
            if _similarity(span, term) >= threshold:
                return True
    return False


def context_bias_is_safe(unbiased, biased, terms, near_threshold=BIAS_NEAR_THRESHOLD):
    """context 로 편향한 결과(biased)가 누출 없이 안전한지 판단한다. 편향본이 새로
    만들어낸 등록어(biased 엔 있고 unbiased 엔 없는)가 무편향본에 음향적 근거(근접
    토막)를 가질 때만 안전하다고 본다. 근거 없는 등록어가 하나라도 있으면 거부."""
    if not biased:
        return False
    entries = [t.strip() for t in terms if t.strip()]
    aliases = vocabulary.alias_map(entries)
    for t in _expand_terms(vocabulary.canonical_terms(entries)):
        if t in biased and t not in unbiased:
            # 영어 표기는 한글로 들린 소리와 글자체가 달라 견줄 수 없으므로, 적어 둔 발음이
            # 무편향본의 어느 토막과 닮았는지도 근거로 인정한다.
            evidence = _has_near_span(unbiased, t, near_threshold) or any(
                _has_near_span(unbiased, a, near_threshold) for a in aliases.get(t, ())
            )
            if not evidence:
                return False
    return True


def correct_terms(text, terms, threshold=SIMILARITY_THRESHOLD):
    """text 안의 근접 오인식을 등록 용어로 교정해 돌려준다.

    항목에 발음이 붙어 있으면(`GitHub(깃허브)`) 그 발음과 소리가 같은 말을 대표 표기로
    바꾼다. 무조건 치환이 아니라 사용자가 적은 발음과 소리가 같을 때만이다."""
    if not text or not terms:
        return text
    entries = [t.strip() for t in terms if t.strip()]
    pairs = [
        (spoken, term)
        for term, spokens in vocabulary.alias_map(entries).items()
        for spoken in spokens
    ]
    cleaned = _expand_terms(vocabulary.canonical_terms(entries))
    # 여러 단어로 된 용어를 먼저 맞춘다(부분 매칭이 긴 구를 깨지 않도록).
    multi = sorted(
        (t for t in cleaned if len(t.split()) > 1),
        key=lambda t: len(t.split()),
        reverse=True,
    )
    single = [
        t for t in cleaned
        if len(t.split()) == 1 and len(_norm(t)) >= MIN_NORM_LEN  # 너무 짧은 용어는 건너뜀
    ]
    result = text
    for term in multi:
        result = _replace_spans(result, term, len(term.split()), threshold)
    if single:
        result = _correct_single_terms(result, single, threshold)
    if pairs:
        result = _apply_aliases(result, pairs, set(cleaned), threshold)
    return result
