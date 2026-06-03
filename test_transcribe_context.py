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
    assert fake.calls[0]["context"] == "각막, 궤양"


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
