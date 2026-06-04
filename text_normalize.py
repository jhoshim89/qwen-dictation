# text_normalize.py
"""말한 한국어 수사를, 단위가 바로 뒤에 붙은 경우에만 아라비아 숫자로 바꾼다.

설계 원칙은 '안전 우선'이다. 한국어 수사는 일반 단어와 소리가 겹친다
('천사'=1004, '이사'=24, '이 개'=this dog). 그래서 다음 조건을 모두 만족할
때만 변환한다.

- 측정 단위(밀리·미터·키로·그램·퍼센트·마리·mm·kg ...)가 바로 붙으면: 한 자리
  수사도 변환한다. 단위 자체가 모호하지 않아 오변환 위험이 낮다.
- 짧은 세는 단위(개·명·번·회·살·년 ...)가 붙으면: 한자어 수사는 두 글자
  이상일 때만 변환한다('이천육년'→2006년은 OK, '이 개'는 그대로). 고유어
  수사는 단위 앞에 띄어쓰기가 있을 때만 변환한다('세 마리'→3마리).
- '이사', '천사' 같은 흔한 동음이의 낱말은 아예 변환하지 않는다.

순수 규칙 기반이라 모든 모호함을 없앨 수는 없다. 이득(측정값)이 큰 쪽으로
보수적으로 맞췄고, 위험한 자리(도='또한' 조사, 만='only')는 단위에서 제외했다.
"""
import re

# 한자어 숫자
SINO_DIGITS = {
    "영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4,
    "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9,
}
SINO_SMALL = {"십": 10, "백": 100, "천": 1000}
SINO_BIG = {"만": 10 ** 4, "억": 10 ** 8, "조": 10 ** 12}
_SINO_CHARS = "".join(list(SINO_DIGITS) + list(SINO_SMALL) + list(SINO_BIG))

# 고유어 숫자(단위 앞 형태 포함)
NATIVE_TENS = {
    "아흔": 90, "여든": 80, "일흔": 70, "예순": 60, "쉰": 50,
    "마흔": 40, "서른": 30, "스물": 20, "스무": 20, "열": 10,
}
NATIVE_ONES = {
    "하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3,
    "넷": 4, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7,
    "여덟": 8, "아홉": 9,
}

# 측정 단위: 모호함이 적어 한 자리 수사도 붙여 변환한다(띄어쓰기 무관).
STRONG_UNITS = [
    "밀리미터", "센티미터", "밀리그램", "밀리리터", "마이크로그램", "킬로그램",
    "퍼센트", "킬로", "키로", "센티", "밀리", "미리", "미터", "그램", "그람",
    "리터", "시시", "마리", "개월", "시간",
    "mm", "cm", "km", "kg", "mg", "ml", "cc",
]
# 짧은 세는 단위: 동음이의 위험이 커서 더 엄격하게(한자어 2글자↑ / 고유어 띄어쓰기) 다룬다.
# 일부러 제외: 도(='또한' 조사), 만(='only'), 시·분·초·일·주·달(시간 동음이의).
WEAK_UNITS = [
    "마이크로리터", "퍼밀", "명", "개", "번", "회", "살", "년", "권", "잔",
    "병", "포", "정", "알", "방울", "그루", "켤레", "송이", "마리",
]

# 흔한 비(非)숫자 동음이의 한자어 음절열 — 절대 변환하지 않는다.
BLOCKLIST = {"이사", "사이", "천사", "구이", "오사", "사사"}

_UNIT_SUFFIX = r"(?![가-힣A-Za-z0-9])"


def _by_len_desc(words):
    return sorted(set(words), key=len, reverse=True)


def _alt(words):
    return "|".join(re.escape(w) for w in _by_len_desc(words))


def _sino_digits_str(run):
    out = []
    for ch in run:
        if ch in SINO_DIGITS:
            out.append(str(SINO_DIGITS[ch]))
        else:
            return None
    return "".join(out) if out else None


def _sino_int(run):
    """한자어 정수 음절열 -> int(실패 시 None)."""
    if not run:
        return None
    has_unit = any((c in SINO_SMALL or c in SINO_BIG) for c in run)
    if not has_unit:
        digits = _sino_digits_str(run)
        return None if digits is None else int(digits)
    total = section = current = 0
    for ch in run:
        if ch in SINO_DIGITS:
            current = SINO_DIGITS[ch]
        elif ch in SINO_SMALL:
            section += (current or 1) * SINO_SMALL[ch]
            current = 0
        elif ch in SINO_BIG:
            chunk = (section + current) or 1
            total += chunk * SINO_BIG[ch]
            section = current = 0
        else:
            return None
    return total + section + current


def _sino_to_number_str(run):
    """'이천육'->'2006', '이점오'->'2.5'. 실패 시 None."""
    if run in BLOCKLIST:
        return None
    if "점" in run:
        parts = run.split("점")
        if len(parts) != 2 or not parts[1]:
            return None
        int_part, frac_part = parts
        ip = 0 if int_part == "" else _sino_int(int_part)
        if ip is None:
            return None
        fd = _sino_digits_str(frac_part)
        if fd is None:
            return None
        return f"{ip}.{fd}"
    value = _sino_int(run)
    return None if value is None else str(value)


def _native_to_number_str(run):
    """'세'->'3', '스물셋'->'23'. 실패 시 None."""
    value = 0
    rest = run
    for tens in _by_len_desc(NATIVE_TENS):
        if rest.startswith(tens):
            value += NATIVE_TENS[tens]
            rest = rest[len(tens):]
            break
    if rest:
        if rest in NATIVE_ONES:
            value += NATIVE_ONES[rest]
        else:
            return None
    return str(value) if value > 0 else None


# 정규식 조각
_SINO_RUN = rf"[{_SINO_CHARS}]+(?:점[{''.join(SINO_DIGITS)}]+)?"
_SINO_RUN2 = rf"[{_SINO_CHARS}]{{2,}}(?:점[{''.join(SINO_DIGITS)}]+)?"
_NATIVE_RUN = (
    r"(?:아흔|여든|일흔|예순|쉰|마흔|서른|스물|스무|열)?"
    r"(?:하나|한|둘|두|셋|세|넷|네|다섯|여섯|일곱|여덟|아홉)?"
)

_STRONG = _alt(STRONG_UNITS)
_WEAK = _alt(WEAK_UNITS)

# 1) 한자어 + 측정 단위(띄어쓰기 무관, 한 자리 허용)
_RE_SINO_STRONG = re.compile(rf"({_SINO_RUN})\s?({_STRONG}){_UNIT_SUFFIX}")
# 2) 한자어(2글자↑) + 짧은 단위(띄어쓰기 무관)
_RE_SINO_WEAK = re.compile(rf"({_SINO_RUN2})\s?({_WEAK}){_UNIT_SUFFIX}")
# 3) 고유어 + (측정/짧은) 단위 — 반드시 띄어쓰기 있을 때만
_RE_NATIVE = re.compile(rf"\b({_NATIVE_RUN})\s({_STRONG}|{_WEAK}){_UNIT_SUFFIX}")


def _sub_sino(match):
    num = _sino_to_number_str(match.group(1))
    if num is None:
        return match.group(0)
    return f"{num}{match.group(2)}"


def _sub_native(match):
    run = match.group(1)
    if not run:
        return match.group(0)
    num = _native_to_number_str(run)
    if num is None:
        return match.group(0)
    return f"{num} {match.group(2)}"


def normalize_numbers(text):
    """단위가 붙은 한국어 수사만 아라비아 숫자로 바꾼 새 문자열을 돌려준다.

    이미 숫자인 부분은 건드리지 않으므로 여러 번 적용해도 결과가 같다(idempotent).
    """
    if not text:
        return text
    out = _RE_SINO_STRONG.sub(_sub_sino, text)
    out = _RE_SINO_WEAK.sub(_sub_sino, out)
    out = _RE_NATIVE.sub(_sub_native, out)
    return out
