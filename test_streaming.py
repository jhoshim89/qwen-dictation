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


def test_streaming_timing_defaults_stay_responsive():
    wd = _load()
    # Measured Qwen inference ~0.1s/pass (mps) -> poll well under the generic 0.8s
    # default so the last words show quickly. Values are hand-tuned; assert the
    # design intent (responsive bounds) rather than exact numbers so tuning is free.
    # See docs/superpowers/plans/2026-06-04-streaming-dictation-defaults.md
    assert 0 < wd.STREAM_INTERVAL <= 0.5
    assert 0.2 <= wd.PAUSE_SILENCE_SEC <= 0.6
    assert 4.0 <= wd.MAX_WINDOW_SEC <= 20.0


def test_stream_loop_wakes_immediately_on_stop_signal(monkeypatch):
    wd = _load()
    rec = _kbd_recorder(wd)
    rec.recording = True
    rec._wake.set()  # 정지 신호가 이미 와 있는 상태
    rec.finalize_on_stop = True
    rec.send_enter_on_stop = False
    ticks = []
    monkeypatch.setattr(rec, "_stream_tick", lambda *a, **k: ticks.append(k))
    monkeypatch.setattr(wd.dictation_history, "add_history", lambda *_: None)
    rec._stream_loop("ko")
    # 일반 틱 없이 마지막 틱(allow_stopped=True) 한 번만 돈다.
    assert len(ticks) == 1
    assert ticks[0].get("allow_stopped") is True


def test_enter_skips_settle_when_final_tick_adds_nothing(monkeypatch):
    wd = _load()
    rec = _kbd_recorder(wd)
    rec.recording = False
    rec.finalize_on_stop = True
    rec.send_enter_on_stop = True
    monkeypatch.setattr(rec, "_stream_tick", lambda *a, **k: None)  # 새 글자 없음
    monkeypatch.setattr(wd.dictation_history, "add_history", lambda *_: None)
    settles = []
    monkeypatch.setattr(rec, "_send_enter", lambda settle=0.03: settles.append(settle))
    rec._stream_loop("ko")
    assert settles == [0.0]  # 변화 없음 → 곧장 엔터


def test_enter_uses_settle_when_final_tick_types_new_text(monkeypatch):
    wd = _load()
    rec = _kbd_recorder(wd)
    rec.recording = False
    rec.finalize_on_stop = True
    rec.send_enter_on_stop = True

    def tick(*a, **k):
        rec.last_typed = "끝말"  # 마지막 틱이 새 글자를 침

    monkeypatch.setattr(rec, "_stream_tick", tick)
    monkeypatch.setattr(wd.dictation_history, "add_history", lambda *_: None)
    settles = []
    monkeypatch.setattr(rec, "_send_enter", lambda settle=0.03: settles.append(settle))
    rec._stream_loop("ko")
    assert settles and settles[0] > 0  # 새 글자 있음 → 반영 대기 후 엔터


def test_history_saved_after_enter(monkeypatch):
    wd = _load()
    rec = _kbd_recorder(wd)
    rec.recording = False
    rec.finalize_on_stop = True
    rec.send_enter_on_stop = True
    monkeypatch.setattr(rec, "_stream_tick", lambda *a, **k: None)
    order = []
    monkeypatch.setattr(rec, "_send_enter", lambda settle=0.03: order.append("enter"))
    monkeypatch.setattr(wd.dictation_history, "add_history", lambda *_: order.append("history"))
    rec._stream_loop("ko")
    assert order == ["enter", "history"]  # 엔터가 기록 저장보다 먼저


def test_type_diff_inserts_additions_via_insert_callable():
    wd = _load()
    inserted = []
    kb = _FakeKeyboard()
    result = wd.type_diff("", "hello", kb, insert=inserted.append)
    assert result == "hello"
    assert inserted == ["hello"]
    assert kb.events == []  # pure insertion uses no keystrokes


def test_type_diff_appends_only_the_new_suffix():
    wd = _load()
    inserted = []
    kb = _FakeKeyboard()
    result = wd.type_diff("abc", "abcde", kb, insert=inserted.append)
    assert result == "abcde"
    assert inserted == ["de"]
    assert kb.events == []


def test_type_diff_backspaces_via_keyboard_then_inserts_via_callable():
    wd = _load()
    from pynput import keyboard
    inserted = []
    kb = _FakeKeyboard()
    result = wd.type_diff("abcX", "abcY", kb, insert=inserted.append)
    assert result == "abcY"
    assert inserted == ["Y"]
    assert kb.events.count(("press", keyboard.Key.backspace)) == 1


def test_type_diff_defaults_insert_to_keyboard_type():
    wd = _load()
    typed = []

    class _KbWithType(_FakeKeyboard):
        def type(self, text):
            typed.append(text)

    wd.type_diff("", "hi", _KbWithType())
    assert typed == ["hi"]


def test_unicode_type_posts_down_and_up_per_char():
    wd = _load()
    posts = []
    wd.unicode_type("hi", _post=lambda tap, ev: posts.append(ev))
    assert len(posts) == 4  # down+up for 'h', down+up for 'i'


def test_unicode_type_empty_posts_nothing():
    wd = _load()
    posts = []
    wd.unicode_type("", _post=lambda tap, ev: posts.append(ev))
    assert posts == []


def test_recorder_type_uses_unicode_inserter(monkeypatch):
    wd = _load()
    captured = {}

    def fake_type_diff(old, new, kb, allow_empty=False, insert=None):
        captured["insert"] = insert
        return new

    monkeypatch.setattr(wd, "type_diff", fake_type_diff)
    rec = _kbd_recorder(wd)
    rec._type("", "hello")
    # When Quartz CGEvents are available, the inserter must be unicode_type.
    # Otherwise _type passes insert=None and type_diff falls back to
    # keyboard_controller.type internally.
    if wd.CGEventCreateKeyboardEvent is not None:
        assert captured["insert"] is wd.unicode_type
    else:
        assert captured["insert"] is None


def test_start_seeds_audio_frames_from_preroll(monkeypatch):
    wd = _load()
    rec = _kbd_recorder(wd)
    rec._preroll.extend([b"aa", b"bb"])
    monkeypatch.setattr(rec, "start_capture", lambda: None)
    monkeypatch.setattr(rec, "_stream_loop", lambda *a, **k: None)
    rec.start("ko")
    assert rec.audio_frames == [b"aa", b"bb"]  # 직전 preroll 이 앞에 깔림
    rec.recording = False


def test_capture_loop_fills_preroll_but_records_only_when_recording():
    wd = _load()
    rec = _kbd_recorder(wd)  # app=None → input_device 기본 ""
    chunks = [b"\x00\x01", b"\x02\x03", b"\x04\x05"]
    state = {"i": 0}

    class FakeStream:
        def read(self, n, exception_on_overflow=False):
            i = state["i"]; state["i"] += 1
            if i >= len(chunks):
                rec._capture_on = False
                return b"\x00\x00"
            return chunks[i]
        def stop_stream(self): pass
        def close(self): pass

    rec._stream = FakeStream()
    rec._open_device = ""      # app.input_device 기본 "" 과 일치 → 재오픈 안 함
    rec._capture_on = True
    rec.recording = False      # 녹음 아님 → audio_frames 엔 안 쌓임
    rec._capture_loop()
    assert len(rec._preroll) > 0       # preroll 은 계속 채워짐
    assert rec.audio_frames == []      # 녹음 중 아니므로 기록 안 됨


def test_capture_loop_appends_to_audio_frames_while_recording():
    wd = _load()
    rec = _kbd_recorder(wd)
    state = {"i": 0}

    class FakeStream:
        def read(self, n, exception_on_overflow=False):
            i = state["i"]; state["i"] += 1
            if i >= 2:
                rec._capture_on = False
            return b"\x01\x02"
        def stop_stream(self): pass
        def close(self): pass

    rec._stream = FakeStream()
    rec._open_device = ""
    rec._capture_on = True
    rec.recording = True       # 녹음 중 → audio_frames 에도 쌓임
    rec._capture_loop()
    assert len(rec.audio_frames) >= 1
