# test_streaming.py
import importlib.util
import numpy as np


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pcm(samples_int16):
    return np.asarray(samples_int16, dtype=np.int16).tobytes()


def test_trailing_silence_true_when_tail_quiet():
    wd = _load()
    # 1초 큰 소리 + 1초 무음, 끝 0.8초가 조용 → True
    loud = list((np.random.RandomState(0).randn(16000) * 6000).astype(np.int16))
    quiet = [0] * 16000
    audio = _pcm(loud + quiet)
    assert wd.trailing_silence(audio, 16000, 1000.0, 0.8) is True


def test_trailing_silence_false_when_tail_loud():
    wd = _load()
    loud = list((np.random.RandomState(1).randn(16000) * 6000).astype(np.int16))
    audio = _pcm(loud + loud)  # 끝까지 시끄러움
    assert wd.trailing_silence(audio, 16000, 1000.0, 0.8) is False


def test_trailing_silence_short_audio_false():
    wd = _load()
    # 0.8초보다 짧으면 아직 쉼 판정 안 함(False)
    audio = _pcm([0] * 1000)
    assert wd.trailing_silence(audio, 16000, 1000.0, 0.8) is False


def test_should_commit_on_pause():
    wd = _load()
    assert wd.should_commit(window_secs=3.0, paused=True, max_secs=12.0) is True


def test_should_commit_on_max_window():
    wd = _load()
    assert wd.should_commit(window_secs=12.5, paused=False, max_secs=12.0) is True


def test_should_not_commit_midspeech():
    wd = _load()
    assert wd.should_commit(window_secs=3.0, paused=False, max_secs=12.0) is False


def _make_recorder(wd, monkeypatch, hypo_by_call):
    # rumps 앱 없이 Recorder 의 스트리밍 부분만 테스트
    class FakeTranscriber:
        def __init__(self): self.calls = 0
        # _transcribe_window 가 호출하는 transcribe_file 흉내는 아래서 monkeypatch
    rec = wd.Recorder.__new__(wd.Recorder)
    rec.audio_lock = __import__("threading").Lock()
    rec.audio_frames = []
    rec.window_start = 0
    rec.committed_text = ""
    rec.last_typed = ""
    rec.typed_log = []
    # type 함수 주입: (old,new)->new, 로그 기록
    rec._type = lambda old, new: (rec.typed_log.append(new) or new)
    # _transcribe_window 를 가설 시퀀스로 대체
    seq = list(hypo_by_call)
    rec._transcribe_window = lambda window_bytes, language: seq.pop(0) if seq else ""
    return rec


def test_stream_tick_types_committed_plus_hypothesis(monkeypatch):
    wd = _load()
    rec = _make_recorder(wd, monkeypatch, ["안녕"])
    # 시끄러운 1초(확정 안 됨: 끝이 시끄러움)
    import numpy as np
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "안녕"
    assert rec.committed_text == ""          # 안 쉬었으니 확정 안 됨
    assert rec.window_start == 0


def test_stream_tick_commits_on_pause_and_advances_window():
    wd = _load()
    import numpy as np
    rec = _make_recorder(wd, None, ["안녕하세요"])
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    quiet = (np.zeros(16000, dtype=np.int16)).tobytes()  # 끝 1초 무음 → 쉼
    with rec.audio_lock:
        rec.audio_frames = [loud, quiet]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "안녕하세요"
    assert rec.committed_text == "안녕하세요"   # 쉬었으니 확정
    assert rec.window_start == 2               # 창 시작이 현재 프레임 끝으로 전진
