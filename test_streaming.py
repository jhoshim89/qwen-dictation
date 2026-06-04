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


def test_pcm_peak_uses_absolute_int16_amplitude():
    wd = _load()
    assert wd.pcm_peak(_pcm([0, -4200, 1200])) == 4200.0


def test_volume_threshold_defaults_match_legacy_values():
    wd = _load()
    silence, start = wd.volume_peak_thresholds(35)
    assert silence == wd.SILENCE_PEAK_THRESHOLD
    assert start == wd.SPEECH_START_PEAK_THRESHOLD


def test_volume_threshold_lower_value_catches_quieter_speech():
    wd = _load()
    _, default_start = wd.volume_peak_thresholds(35)
    _, quiet_start = wd.volume_peak_thresholds(10)
    assert quiet_start < default_start


def test_find_input_device_index_matches_named_microphone():
    wd = _load()

    class FakePyAudio:
        devices = [
            {"name": "Speakers", "maxInputChannels": 0},
            {"name": "MATA STUDIO C10", "maxInputChannels": 2},
        ]
        def get_device_count(self): return len(self.devices)
        def get_device_info_by_index(self, index): return self.devices[index]

    pa = FakePyAudio()
    assert wd.find_input_device_index(pa, "MATA STUDIO C10") == 1
    assert wd.find_input_device_index(pa, "missing") is None
    assert wd.find_input_device_index(pa, "") is None


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
    rec.recording = True
    rec.rebaseline_pending = False
    rec.self_type_guard_until = 0.0
    rec.app = type("App", (), {"min_volume": 35})()
    rec.transcriber = FakeTranscriber()
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


def test_stream_tick_discards_quiet_window_before_transcribing():
    wd = _load()
    rec = _make_recorder(wd, None, ["잘못 나온 말"])
    rec.app = type("App", (), {"min_volume": 35})()
    rec.transcriber = type("Transcriber", (), {})()
    quiet_noise = (np.ones(16000, dtype=np.int16) * 2200).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [quiet_noise]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == ""
    assert rec.typed_log == []
    assert rec.window_start == 1


def test_stream_tick_low_min_volume_allows_quiet_window():
    wd = _load()
    rec = _make_recorder(wd, None, ["작게 말함"])
    rec.app = type("App", (), {"min_volume": 10})()
    rec.transcriber = type("Transcriber", (), {})()
    quiet_speech = (np.ones(16000, dtype=np.int16) * 2200).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [quiet_speech]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "작게 말함"
    assert rec.transcriber.min_volume == 10


def test_rebaseline_sets_pending_flag():
    wd = _load()
    rec = wd.Recorder.__new__(wd.Recorder)
    rec.rebaseline_pending = False
    wd.Recorder.rebaseline(rec)
    assert rec.rebaseline_pending is True


def test_stream_tick_consumes_rebaseline_and_resets_ownership():
    wd = _load()
    rec = _make_recorder(wd, None, ["새 발화"])
    # 이전 받아쓰기 흔적 + 사용자가 직접 고친 뒤 재기준화 요청
    with rec.audio_lock:
        rec.audio_frames = [b"\x00\x00" * 16000]
    rec.committed_text = "이전 글자"
    rec.last_typed = "이전 글자"
    rec.window_start = 0
    rec.rebaseline_pending = True
    wd.Recorder._stream_tick(rec, language="Korean")
    # 기준점이 현재 프레임 끝으로 리셋되어 빈 창 → 이번 틱은 타이핑하지 않음
    assert rec.rebaseline_pending is False
    assert rec.committed_text == ""
    assert rec.last_typed == ""
    assert rec.window_start == 1
    assert rec.typed_log == []


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


def test_repetition_hallucination_is_removed_from_live_typing():
    wd = _load()
    rec = _make_recorder(wd, None, ["내 내 내"])
    rec.last_typed = "내 내"
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == ""
    assert rec.typed_log == [""]


def test_repetition_hallucination_filter_keeps_normal_sentence():
    wd = _load()
    assert wd.looks_like_repetition_hallucination("내 내 내") is True
    assert wd.looks_like_repetition_hallucination("내가 말한 내용") is False


def test_pause_noise_filler_filter_rejects_short_response_only():
    wd = _load()
    assert wd.looks_like_pause_noise_filler("어.") is True
    assert wd.looks_like_pause_noise_filler("네") is True
    assert wd.looks_like_pause_noise_filler("네 알겠습니다") is False


def test_punctuation_only_filter_keeps_contextual_punctuation():
    wd = _load()
    assert wd.looks_like_punctuation_only(".") is True
    assert wd.looks_like_punctuation_only("?") is True
    assert wd.looks_like_punctuation_only("...!?") is True
    assert wd.looks_like_punctuation_only("안녕하세요.") is False
    assert wd.looks_like_punctuation_only("괜찮나요?") is False


def test_stream_tick_removes_short_filler_at_pause():
    wd = _load()
    rec = _make_recorder(wd, None, ["어."])
    rec.last_typed = "어"
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    quiet = (np.zeros(16000, dtype=np.int16)).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud, quiet]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == ""
    assert rec.committed_text == ""
    assert rec.typed_log == [""]


def test_stream_tick_removes_punctuation_only_at_pause():
    wd = _load()
    rec = _make_recorder(wd, None, ["."])
    rec.last_typed = "."
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    quiet = (np.zeros(16000, dtype=np.int16)).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud, quiet]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == ""
    assert rec.committed_text == ""
    assert rec.typed_log == [""]


def test_stream_loop_skips_final_tick_after_enter_send():
    wd = _load()
    rec = wd.Recorder.__new__(wd.Recorder)
    rec.recording = False
    rec.finalize_on_stop = False
    rec.window_start = 99
    rec.committed_text = "old"
    rec.last_typed = "old"
    rec.ticks = []
    rec._stream_tick = lambda language, allow_stopped=False: rec.ticks.append(allow_stopped)
    wd.Recorder._stream_loop(rec, language="Korean")
    assert rec.ticks == []


def test_stream_loop_keeps_final_tick_for_regular_stop():
    wd = _load()
    rec = wd.Recorder.__new__(wd.Recorder)
    rec.recording = False
    rec.finalize_on_stop = True
    rec.ticks = []
    rec._stream_tick = lambda language, allow_stopped=False: rec.ticks.append(allow_stopped)
    wd.Recorder._stream_loop(rec, language="Korean")
    assert rec.ticks == [True]


class _FakeKeyboard:
    def __init__(self):
        self.events = []

    def press(self, key):
        self.events.append(("press", key))

    def release(self, key):
        self.events.append(("release", key))


class _FakeTranscriber:
    def __init__(self):
        self.pykeyboard = _FakeKeyboard()


def _kbd_recorder(wd):
    return wd.Recorder(_FakeTranscriber(), app=None)


def test_stop_sets_send_enter_only_when_finalize_and_send_enter():
    wd = _load()
    rec = _kbd_recorder(wd)
    rec.stop(finalize=True, send_enter=True)
    assert rec.send_enter_on_stop is True
    rec.stop(finalize=False, send_enter=True)
    assert rec.send_enter_on_stop is False
    rec.stop(finalize=True, send_enter=False)
    assert rec.send_enter_on_stop is False


def test_stream_loop_sends_enter_when_flag_set(monkeypatch):
    wd = _load()
    from pynput import keyboard
    rec = _kbd_recorder(wd)
    rec.recording = False
    rec.finalize_on_stop = True
    rec.send_enter_on_stop = True
    monkeypatch.setattr(rec, "_stream_tick", lambda *a, **k: None)
    monkeypatch.setattr(wd.dictation_history, "add_history", lambda *_: None)
    rec._stream_loop("ko")
    kb = rec.transcriber.pykeyboard
    assert ("press", keyboard.Key.enter) in kb.events
    assert ("release", keyboard.Key.enter) in kb.events


def test_stream_loop_no_enter_when_flag_unset(monkeypatch):
    wd = _load()
    rec = _kbd_recorder(wd)
    rec.recording = False
    rec.finalize_on_stop = True
    rec.send_enter_on_stop = False
    monkeypatch.setattr(rec, "_stream_tick", lambda *a, **k: None)
    monkeypatch.setattr(wd.dictation_history, "add_history", lambda *_: None)
    rec._stream_loop("ko")
    assert rec.transcriber.pykeyboard.events == []


def test_streaming_timing_defaults_measured_on_this_machine():
    wd = _load()
    # Measured Qwen inference ~0.1s/pass (mps) -> poll faster than generic 0.8s default.
    # See docs/superpowers/plans/2026-06-04-streaming-dictation-defaults.md
    assert wd.STREAM_INTERVAL == 0.4
    assert wd.PAUSE_SILENCE_SEC == 0.4
    assert wd.MAX_WINDOW_SEC == 12.0
