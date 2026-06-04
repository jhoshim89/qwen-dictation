import importlib.util

import app_paths
import vocabulary


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResult:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, context="", language=None, **kw):
        self.calls.append({"audio": audio, "context": context, "language": language})
        return [_FakeResult("녹음 결과")]


def _write_wav(path, samples):
    import numpy as np
    import soundfile as sf
    sf.write(str(path), np.asarray(samples, dtype="int16"), 16000)


def test_transcribe_passes_vocabulary_context(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["각막", "궤양"])

    # 말소리 수준 에너지의 wav (게이트 통과해야 함)
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(1).randn(16000) * 5000))

    tr = wd.SpeechTranscriber("cpu", None)
    fake = _FakeModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)

    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "녹음 결과"
    assert fake.calls[0]["context"] == "전문 용어: 각막, 궤양"


def test_transcribe_skips_silent_audio(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "v.json"))
    vocabulary.save_vocabulary(["궤양", "각막", "염색"])

    sil = tmp_path / "sil.wav"
    _write_wav(sil, np.zeros(16000))  # 무음

    tr = wd.SpeechTranscriber("cpu", None)
    called = []
    monkeypatch.setattr(tr, "get_model", lambda: called.append(True) or _FakeModel())

    out = tr.transcribe_file(str(sil), language="Korean")
    assert out == ""          # 무음 → echo 방지 위해 건너뜀
    assert called == []        # 모델 호출 안 됨


def test_looks_like_vocab_echo():
    wd = _load()
    vocab = ["궤양", "각막", "염색", "Qwen"]
    # 등록 단어들로만 → echo
    assert wd.looks_like_vocab_echo("궤양, 각막, 염색.", vocab) is True
    assert wd.looks_like_vocab_echo("각막 염색", vocab) is True
    # 실제 발화(등록 안 된 말 포함) → echo 아님
    assert wd.looks_like_vocab_echo("각막궤양 관찰 결과입니다.", vocab) is False
    # 단어 1개 → 실제 발화일 수 있어 건드리지 않음
    assert wd.looks_like_vocab_echo("각막", vocab) is False
    # vocab 없으면 항상 False
    assert wd.looks_like_vocab_echo("각막 염색", []) is False


def test_echo_result_retranscribes_without_context(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["궤양", "각막", "염색"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(2).randn(16000) * 5000))

    class EchoThenRealModel:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio, context="", language=None, **kw):
            self.calls.append(context)
            # context 있으면 echo, 없으면 진짜
            text = "궤양, 각막, 염색." if context else "각막궤양 관찰 결과입니다."
            return [_FakeResult(text)]

    tr = wd.SpeechTranscriber("cpu", None)
    fake = EchoThenRealModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)
    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "각막궤양 관찰 결과입니다."   # echo 감지 후 context 없이 재전사 결과
    assert fake.calls[0] != "" and fake.calls[1] == ""  # 1차 context, 2차 무context


def test_transcribe_does_not_apply_dictionary_replacements(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["Qwen"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(3).randn(16000) * 5000))

    class MisheardModel:
        def transcribe(self, audio, context="", language=None, **kw):
            return [_FakeResult("큐엔 테스트")]

    tr = wd.SpeechTranscriber("cpu", None)
    monkeypatch.setattr(tr, "get_model", lambda: MisheardModel())
    assert tr.transcribe_file(str(wav), language="Korean") == "큐엔 테스트"


def test_no_apply_dictionary_symbol():
    wd = _load()
    assert not hasattr(wd, "apply_dictionary")


def test_looks_like_vocab_echo_handles_multiword():
    wd = _load()
    vocab = ["corneal ulcer", "cornea", "fluorescein"]
    # 여러 단어 등록어로만 → echo (이전 토큰 기반 가드는 못 잡던 케이스)
    assert wd.looks_like_vocab_echo("corneal ulcer, cornea, fluorescein", vocab) is True
    # 실제 문장 안에 포함 → echo 아님
    assert wd.looks_like_vocab_echo("the corneal ulcer healed well", vocab) is False


def test_transcribe_drops_context_on_weak_audio(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["각막", "궤양"])
    # 무음은 아니지만(>silence) 분명한 말소리 임계 미만(<speech)인 약한 신호
    t = np.arange(16000)
    weak = (2000 * np.sin(2 * np.pi * 220 * t / 16000)).astype("int16")
    wav = tmp_path / "weak.wav"
    sf.write(str(wav), weak, 16000)
    tr = wd.SpeechTranscriber("cpu", None)
    fake = _FakeModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)
    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "녹음 결과"
    assert fake.calls[0]["context"] == ""   # 약한 소리 → context 비움(echo 차단)


def test_transcribe_prepends_domain_context(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["녹내장"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(7).randn(16000) * 5000))

    tr = wd.SpeechTranscriber("cpu", None)
    tr.domain_context = "수의안과 진료"
    fake = _FakeModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)

    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "녹음 결과"
    assert fake.calls[0]["context"] == "수의안과 진료. 전문 용어: 녹내장"


def test_looks_like_domain_echo():
    wd = _load()
    assert wd.looks_like_domain_echo("수의안과 진료", "수의안과 진료.") is True
    assert wd.looks_like_domain_echo("녹내장입니다", "수의안과 진료") is False
    assert wd.looks_like_domain_echo("anything", "") is False
    assert wd.looks_like_domain_echo("", "수의안과 진료") is False


def test_looks_like_domain_echo_partial_and_dash():
    wd = _load()
    DOM = "수의안과 진료와 소프트웨어 개발 — 안과 검사 용어와 프로그래밍 용어 위주"
    # 분야 문장의 앞부분만 새는 부분 echo (실시간 첫 짧은 조각에서 자주 발생)
    assert wd.looks_like_domain_echo("수의안과 진료와 소프트웨어 개발", DOM) is True
    # em-dash 를 빼거나 하이픈으로 바꿔 뱉은 전체 echo
    assert wd.looks_like_domain_echo(
        "수의안과 진료와 소프트웨어 개발 안과 검사 용어와 프로그래밍 용어 위주", DOM) is True
    assert wd.looks_like_domain_echo(
        "수의안과 진료와 소프트웨어 개발 - 안과 검사 용어와 프로그래밍 용어 위주", DOM) is True
    # 실제 단어와 분야 문장이 섞여 새는 leakage(혼합) — 실사용에서 가장 흔한 증상
    assert wd.looks_like_domain_echo(
        "녹내장 수의안과 진료와 소프트웨어 개발. 안과 검사 용어와 프로그래밍 용어 위주", DOM) is True
    assert wd.looks_like_domain_echo(
        "수의안과 진료와 소프트웨어 개발 녹내장", DOM) is True
    # 실제 발화/등록 단어는 보존(echo 아님)
    assert wd.looks_like_domain_echo("녹내장", DOM) is False
    assert wd.looks_like_domain_echo("안압", DOM) is False
    assert wd.looks_like_domain_echo("녹내장 소견이 보입니다", DOM) is False
    assert wd.looks_like_domain_echo("오늘 점심 뭐 먹지", DOM) is False


def test_domain_echo_retranscribes_without_context(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["녹내장"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(8).randn(16000) * 5000))

    class EchoDomainModel:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio, context="", language=None, **kw):
            self.calls.append(context)
            # 분야 문장이 system 지시문에 들어가면 흘림(leakage), 없으면 진짜.
            if "수의안과" in context:
                return [_FakeResult("수의안과 진료")]
            return [_FakeResult("녹내장입니다")]

    tr = wd.SpeechTranscriber("cpu", None)
    tr.domain_context = "수의안과 진료"
    fake = EchoDomainModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)

    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "녹내장입니다"
    assert "수의안과" in fake.calls[0]            # 1차는 분야 문장 포함
    assert fake.calls[1] == "전문 용어: 녹내장"   # 2차는 분야 문장만 빼고 단어장 라벨 유지


def test_domain_leakage_mixed_keeps_vocab(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["녹내장"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(9).randn(16000) * 5000))

    class MixedLeakModel:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio, context="", language=None, **kw):
            self.calls.append(context)
            # 실제 단어 + 분야 문장을 섞어 흘림. 분야 문장 없으면 깨끗한 단어만.
            if "수의안과" in context:
                return [_FakeResult("녹내장 수의안과 진료. 안과 검사 용어 위주")]
            return [_FakeResult("녹내장")]

    tr = wd.SpeechTranscriber("cpu", None)
    tr.domain_context = "수의안과 진료. 안과 검사 용어 위주"
    fake = MixedLeakModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)

    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "녹내장"                        # 분야 문장 leakage 제거, 실제 단어만 남음
    assert fake.calls[1] == "전문 용어: 녹내장"   # 단어장 biasing(라벨) 은 유지된 채 재전사


def test_current_config_includes_domain_context():
    import types
    wd = _load()
    stub = types.SimpleNamespace(
        current_language="ko", max_time=300, input_device="",
        hold_key="cmd_r", toggle_key="alt_r", min_volume=35,
        edit_interrupt_mode="stop", hold_send_enter=True,
        domain_context="수의안과 진료",
    )
    cfg = wd.StatusBarApp.current_config(stub)
    assert cfg["domain_context"] == "수의안과 진료"


def test_vocab_terms_in_text_finds_mixed_and_glued():
    wd = _load()
    vocab = ["녹내장", "안압"]
    # 실제 말에 섞여도, 조사가 붙어도 잡는다(부분문자열, 공백/구두점 무시).
    assert wd.vocab_terms_in_text("오늘 환자 녹내장 봤어", vocab) == ["녹내장"]
    assert wd.vocab_terms_in_text("녹내장이 보입니다.", vocab) == ["녹내장"]
    assert wd.vocab_terms_in_text("점심 뭐 먹지", vocab) == []
    assert wd.vocab_terms_in_text("녹내장", []) == []


def test_unconfirmed_vocab_term_replaced_by_plain(tmp_path, monkeypatch):
    # 편향(context) 켜면 환각으로 녹내장이 끼고, 끄면 깨끗 → 음향이 뒷받침 안 하므로 제거.
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["녹내장"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(11).randn(16000) * 5000))

    class HallucinatedMixModel:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio, context="", language=None, **kw):
            self.calls.append(context)
            text = "오늘 환자 녹내장 봤어요" if context else "오늘 환자 봤어요"
            return [_FakeResult(text)]

    tr = wd.SpeechTranscriber("cpu", None)
    fake = HallucinatedMixModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)
    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "오늘 환자 봤어요"                # 환각 등록 단어 제거(음향 결과로 대체)
    assert fake.calls[0] != "" and fake.calls[1] == ""   # 1차 편향, 2차 교차확인용 plain


def test_confirmed_vocab_term_is_kept(tmp_path, monkeypatch):
    # 힌트를 끄든 켜든 녹내장이 나오면(흔한 말) 진짜 발화 → 살린다.
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["녹내장"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(12).randn(16000) * 5000))

    class RealWordModel:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio, context="", language=None, **kw):
            self.calls.append(context)
            return [_FakeResult("녹내장 소견입니다")]

    tr = wd.SpeechTranscriber("cpu", None)
    fake = RealWordModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)
    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "녹내장 소견입니다"     # plain 도 같은 단어 → 확인됨 → 유지
    assert fake.calls[1] == ""            # 교차확인 plain 패스는 돌았음


def test_looks_like_context_label_echo():
    wd = _load()
    # context 머리표가 출력에 들어오면 echo (사용자가 말하는 내용이 아님)
    assert wd.looks_like_context_label_echo("전문 용어: 녹내장, 안압") is True
    assert wd.looks_like_context_label_echo("전문 용어: 아무거나 지어낸 말") is True
    # 실제 발화엔 머리표가 없다
    assert wd.looks_like_context_label_echo("녹내장 환자를 봤어요") is False
    assert wd.looks_like_context_label_echo("") is False


def test_labeled_context_echo_dropped_even_with_unknown_terms(tmp_path, monkeypatch):
    # 라이브 버그 재현: 모델이 vocab 에 없는 분야 용어를 '전문 용어:' 라벨째 환각.
    # 기존 단어/분야 echo 가드는 (vocab 매칭이 안 돼) 못 잡는다 → 라벨로 잡아야 함.
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["Qwen"])  # 실제 vocab 엔 녹내장/안압 없음
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(21).randn(16000) * 5000))

    class LabelEchoModel:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio, context="", language=None, **kw):
            self.calls.append(context)
            if context:
                return [_FakeResult("전문 용어: 녹내장, 안압")]
            return [_FakeResult("하나")]

    tr = wd.SpeechTranscriber("cpu", None)
    tr.domain_context = "수의안과 진료"
    fake = LabelEchoModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)
    out = tr.transcribe_file(str(wav), language="Korean")
    assert "전문 용어" not in out      # 머리표가 출력에 남으면 안 됨
    assert out == "하나"               # context 빼고 재전사한 진짜 결과
    assert fake.calls[0] != "" and fake.calls[-1] == ""  # 1차 context, 마지막 무context
