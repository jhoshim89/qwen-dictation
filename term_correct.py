"""받아쓴 텍스트를 등록 용어로 사후 교정한다.

모델에는 용어 목록을 주지 않으므로(누출 0) 인식은 순수 음향으로만 이뤄지고, 여기서
'소리가 거의 같은' 토막만 등록 용어로 바꾼다. 한국어는 NFD 로 음절을 자모로 분해해
소리 단위로 비교한다(계양↔궤양). 같은 글자체 근접 오인식이 대상이며, 교차 글자체
(영어↔한글)는 비교가 불가능해 손대지 않는다(한계).
"""
import re
import unicodedata
from difflib import SequenceMatcher

# "남들 하는 만큼": 유사도가 이 값 이상일 때만 교체한다(멀쩡한 말 오교체 방지).
SIMILARITY_THRESHOLD = 0.8
# 자모로 분해했을 때 이보다 짧은 용어는 fuzzy 매칭하지 않는다(짧으면 우연 매칭 위험).
MIN_NORM_LEN = 4

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _norm(text):
    # NFD: 한글 음절 → 자모(초/중/종성)로 분해. 소리 단위 비교가 되고, 라틴 문자는
    # 소문자화로 대소문자 차이를 흡수한다.
    return unicodedata.normalize("NFD", text).lower()


def _similarity(a, b):
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _replace_spans(text, term, n, threshold):
    """text 안에서 n개 단어로 된 토막이 term 과 임계 이상 비슷하면 term 으로 바꾼다."""
    matches = list(_WORD_RE.finditer(text))
    if len(matches) < n:
        return text
    out = []
    last = 0
    i = 0
    while i <= len(matches) - n:
        span_start = matches[i].start()
        span_end = matches[i + n - 1].end()
        span = text[span_start:span_end]
        if span != term and _similarity(span, term) >= threshold:
            out.append(text[last:span_start])
            out.append(term)
            last = span_end
            i += n
        else:
            i += 1
    out.append(text[last:])
    return "".join(out)


def correct_terms(text, terms, threshold=SIMILARITY_THRESHOLD):
    """text 안의 근접 오인식을 등록 용어로 교정해 돌려준다."""
    if not text or not terms:
        return text
    # 여러 단어로 된 용어를 먼저 맞춘다(부분 매칭이 긴 구를 깨지 않도록).
    ordered = sorted(
        {t.strip() for t in terms if t.strip()},
        key=lambda t: len(t.split()),
        reverse=True,
    )
    result = text
    for term in ordered:
        if len(_norm(term)) < MIN_NORM_LEN:
            continue  # 너무 짧은 용어는 fuzzy 건너뜀
        result = _replace_spans(result, term, len(term.split()), threshold)
    return result
