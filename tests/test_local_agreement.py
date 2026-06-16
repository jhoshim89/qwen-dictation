import importlib.util


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agreed_word_prefix_returns_common_leading_words():
    wd = _load()
    # 마지막 단어가 갈리면(반갑 vs 반갑습니다) 그 앞까지만 합의
    assert wd.agreed_word_prefix("안녕 반갑", "안녕 반갑습니다") == "안녕"
    # 앞이 다 같고 뒤만 늘어나면 공통 앞부분 전체가 합의
    assert wd.agreed_word_prefix("안녕 반갑습니다", "안녕 반갑습니다 또 봐요") == "안녕 반갑습니다"


def test_agreed_word_prefix_empty_and_disjoint_are_empty():
    wd = _load()
    assert wd.agreed_word_prefix("", "안녕") == ""
    assert wd.agreed_word_prefix("안녕", "") == ""
    assert wd.agreed_word_prefix("가 나 다", "라 마 바") == ""


def test_agreed_word_prefix_is_word_level_not_substring():
    wd = _load()
    # '안녕'은 '안녕하세요'의 부분문자열이지만 다른 단어 → 합의 아님
    assert wd.agreed_word_prefix("안녕", "안녕하세요") == ""
