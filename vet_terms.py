# vet_terms.py
"""수의안과 받아쓰기에서 자주 나는 오인식 교정쌍.

값은 '잘못 들린 표기' -> '올바른 표기'. 본 테스트 중 실제로 관찰된 것만
보수적으로 담는다. 사용자는 대시보드에서 자기 용어를 추가한다.
"""

VET_TERMS = {
    "괴양": "궤양",      # 형광 염색 테스트 중 관찰
    "강막": "각막",      # '강막궤양' 오인식 관찰
    "영색": "염색",      # '형광 영색' 오인식 관찰
}


def merge_terms_into(existing):
    """기존 사전(dict)에 VET_TERMS 중 빠진 키만 더해 새 dict 반환.

    사용자가 이미 정의한 키는 절대 덮어쓰지 않는다. 원본은 변경하지 않는다.
    """
    merged = dict(existing)
    for k, v in VET_TERMS.items():
        if k not in merged:
            merged[k] = v
    return merged
