"""사용자가 받아쓴 글자를 직접 고친 것에서 '잘못 들은 말'만 추려 낸다.

받아쓰기 직후의 입력창 글자(before)와 나중에 다시 읽은 글자(after)를 견주어, 우리가
넣은 구간 안에서 바뀐 어절만 뽑는다. 문장을 새로 쓴 것(오인식이 아니라 내용 변경)은
소리 유사도로 걸러 낸다 — 잘못 들은 말은 소리가 거의 같고(0.8 안팎), 새로 쓴 문장은
멀다(0.6 아래). 그 사이인 0.7 을 경계로 둔다.

여기서는 판단만 하고 저장은 하지 않는다. 입력창 원문은 호출한 쪽에서 곧바로 버린다.
"""
import difflib
import re

import term_correct

# 소리가 이만큼 비슷해야 '같은 말을 잘못 들은 것'으로 본다.
# 실측(같은 글자체 기준): 진짜 오인식은 0.67~0.88 — 현관→형광 0.67, 괴양→궤양 0.80,
# 강막→각막 0.83, 농내장→녹내장 0.88. 사용자가 문장을 새로 쓴 경우는 0.21~0.60 —
# 소견은→특이사항 없음 0.24, 있습니다→확인이 필요합니다 0.45, 검사를 했습니다→환자가
# 왔습니다 0.60. 두 무리 사이(0.60~0.67)의 가운데를 경계로 둔다.
SOUND_ALIKE_MIN = 0.63
# 자모 길이가 이만큼은 비슷해야 한다. 잘못 들은 말은 길이가 거의 같고(실측 1.00),
# 새로 쓴 문장은 짧아지거나 길어진다(0.47~0.95).
LEN_RATIO_MIN = 0.8
# 어절 수가 이보다 많이 달라지면 용어 교정이 아니라 문장 고쳐 쓰기로 본다.
# 1 까지 허용하는 것은 띄어쓰기가 붙거나 떨어지는 경우('현관 염색'↔'형광염색') 때문이다.
MAX_WORD_COUNT_DIFF = 1
# 한 글자 교정은 우연 일치가 많아 배우지 않는다.
MIN_TERM_CHARS = 2
# 한 번에 배울 수 있는 최대 개수. 사용자가 문단을 통째로 고쳐도 폭주하지 않게 한다.
MAX_CORRECTIONS_PER_EDIT = 5
# 어절이 이보다 많이 묶인 덩어리는 용어가 아니라 문장이므로 배우지 않는다.
MAX_TERM_WORDS = 3

_WORD_RE = re.compile(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣._+-]*")


def _compact(text):
    return "".join((text or "").split())


def _looks_like_term(text):
    """등록할 만한 용어 모양인지(글자가 있고, 너무 길지 않고, 어절 수가 적은지)."""
    if not text or len(text) < MIN_TERM_CHARS:
        return False
    words = text.split()
    if len(words) > MAX_TERM_WORDS:
        return False
    return bool(_WORD_RE.search(text))


def extract_corrections(typed_text, before, after):
    """(잘못 들은 말, 사용자가 고친 말) 쌍을 돌려준다.

    typed_text: 이번 받아쓰기로 우리가 넣은 글자. 이 안에 있던 말만 대상으로 삼는다
                (사용자가 문서의 다른 곳을 고친 것은 우리 일이 아니다).
    before:     받아쓴 직후 입력창 전체 글자.
    after:      나중에 다시 읽은 입력창 전체 글자.
    """
    if not before or not after or before == after or not typed_text:
        return []
    typed_compact = _compact(typed_text)
    if not typed_compact:
        return []

    before_words = _WORD_RE.findall(before)
    after_words = _WORD_RE.findall(after)
    if not before_words or not after_words:
        return []

    pairs = []
    opcodes = difflib.SequenceMatcher(a=before_words, b=after_words).get_opcodes()
    for tag, i1, i2, j1, j2 in opcodes:
        if tag != "replace":
            # 지우거나 새로 쓴 것은 오인식 근거가 약해 배우지 않는다.
            continue
        wrong = " ".join(before_words[i1:i2]).strip()
        right = " ".join(after_words[j1:j2]).strip()
        if not wrong or not right or wrong == right:
            continue
        # 우리가 넣은 구간 안의 말만 배운다.
        if _compact(wrong) not in typed_compact:
            continue
        if not _looks_like_term(right):
            continue
        if abs(len(wrong.split()) - len(right.split())) > MAX_WORD_COUNT_DIFF:
            continue
        if term_correct._len_ratio(wrong, right) < LEN_RATIO_MIN:
            continue
        if term_correct._similarity(wrong, right) < SOUND_ALIKE_MIN:
            continue
        pairs.append((wrong, right))

    # 같은 고침이 한 번의 편집 안에서 여러 번 나와도 한 번으로 센다.
    unique = list(dict.fromkeys(pairs))
    return unique[:MAX_CORRECTIONS_PER_EDIT]
