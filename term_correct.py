"""받아쓴 텍스트를 등록 용어로 사후 교정한다.

모델에는 용어 목록을 주지 않으므로(누출 0) 인식은 순수 음향으로만 이뤄지고, 여기서
'소리가 거의 같은' 토막만 등록 용어로 바꾼다. 한국어는 NFD 로 음절을 자모로 분해해
소리 단위로 비교한다(계양↔궤양). 같은 글자체 근접 오인식이 대상이며, 교차 글자체
(영어↔한글)는 비교가 불가능해 손대지 않는다(한계).

한 단어 용어는 어절마다 조사/어미를 떼고 '줄기'만 비교한다 — '커밋하고'처럼 뒤에 말이
붙어 한 덩어리가 돼도 줄기('커밋')를 교정하고 조사('하고')는 그대로 둔다. 길이 가드로
등록어의 앞부분과 겹치는 짧은 진짜 단어를 부풀리는 것(각막→각막궤양)을 막는다.
"""
import re
import unicodedata
from difflib import SequenceMatcher

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
    for t in _expand_terms(t.strip() for t in terms if t.strip()):
        if t in biased and t not in unbiased:
            if not _has_near_span(unbiased, t, near_threshold):
                return False
    return True


def correct_terms(text, terms, threshold=SIMILARITY_THRESHOLD):
    """text 안의 근접 오인식을 등록 용어로 교정해 돌려준다."""
    if not text or not terms:
        return text
    cleaned = _expand_terms(t.strip() for t in terms if t.strip())
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
    return result
