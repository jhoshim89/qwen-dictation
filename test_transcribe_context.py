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


def test_transcribe_passes_vocabulary_context(tmp_path, monkeypatch):
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["각막", "궤양"])

    tr = wd.SpeechTranscriber("cpu", None)
    fake = _FakeModel()
    monkeypatch.setattr(tr, "get_model", lambda size: fake)

    out = tr.transcribe_file("/tmp/x.wav", language="Korean", model_size="1.7b")
    assert out == "녹음 결과"
    assert fake.calls[0]["context"] == "각막, 궤양"


def test_no_apply_dictionary_symbol():
    wd = _load()
    assert not hasattr(wd, "apply_dictionary")
