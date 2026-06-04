import text_normalize as tn


# --- 변환되어야 하는 경우 ---

def test_sino_with_measurement_units():
    assert tn.normalize_numbers("삼 밀리") == "3밀리"
    assert tn.normalize_numbers("오 키로") == "5키로"
    assert tn.normalize_numbers("이십 퍼센트") == "20퍼센트"
    assert tn.normalize_numbers("십 밀리리터") == "10밀리리터"


def test_sino_decimal_with_units():
    assert tn.normalize_numbers("이점오 밀리그램") == "2.5밀리그램"
    assert tn.normalize_numbers("삼점일사 미터") == "3.14미터"


def test_sino_two_or_more_syllables_with_weak_units():
    assert tn.normalize_numbers("이천육년") == "2006년"
    assert tn.normalize_numbers("삼십오 번") == "35번"
    assert tn.normalize_numbers("이십사 명") == "24명"


def test_native_counts_require_space():
    assert tn.normalize_numbers("세 마리") == "3 마리"
    assert tn.normalize_numbers("두 개") == "2 개"
    assert tn.normalize_numbers("스물셋 개") == "23 개"


def test_latin_units():
    assert tn.normalize_numbers("오 mg") == "5mg"
    assert tn.normalize_numbers("이십 kg") == "20kg"


def test_inside_a_sentence():
    assert tn.normalize_numbers("각막궤양 깊이가 이점오 밀리 정도입니다") == \
        "각막궤양 깊이가 2.5밀리 정도입니다"


def test_idempotent():
    once = tn.normalize_numbers("삼 밀리")
    assert tn.normalize_numbers(once) == once


# --- 절대 변환되면 안 되는 경우(동음이의 보호) ---

def test_common_homophone_words_untouched():
    # 단위가 안 붙으면 숫자처럼 보여도 그대로 둔다.
    assert tn.normalize_numbers("천사가 내려왔다") == "천사가 내려왔다"
    assert tn.normalize_numbers("이사 준비") == "이사 준비"
    assert tn.normalize_numbers("우리 사이") == "우리 사이"


def test_single_sino_with_weak_unit_not_converted():
    # '이 개'(this dog)를 '2개'로 바꾸면 안 된다. 한자어 한 글자 + 짧은 단위는 보호.
    assert tn.normalize_numbers("이 개가 아픕니다") == "이 개가 아픕니다"
    assert tn.normalize_numbers("그 사 명은") == "그 사 명은"


def test_blocklisted_runs_with_units_not_converted():
    # '이사 명단'이 '24명단'이 되지 않도록 블록리스트가 막는다.
    assert tn.normalize_numbers("이사 명단") == "이사 명단"


def test_particle_homophone_units_excluded():
    # 도(='또한' 조사), 만(='only')은 단위에서 빠져 있어 변환되지 않는다.
    assert tn.normalize_numbers("천사도 울었다") == "천사도 울었다"
    assert tn.normalize_numbers("만년필") == "만년필"


def test_no_unit_no_change():
    assert tn.normalize_numbers("이천육") == "이천육"
    assert tn.normalize_numbers("그냥 텍스트") == "그냥 텍스트"
