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
    rec.defer_typing_until_stop = False
    rec.append_only_until_stop = False
    rec.app = type("App", (), {"min_volume": 35})()
    rec.transcriber = FakeTranscriber()
    rec.typed_log = []
    # type 함수 주입: (old,new)->new, 로그 기록
    rec._type = lambda old, new, append_only=False: (rec.typed_log.append(new) or new)
    # _transcribe_window 를 가설 시퀀스로 대체
    seq = list(hypo_by_call)
    # context= 는 확정 시점 편향 호출에서 들어온다. 기본 스텁은 무시하고 같은 시퀀스를
    # 소비한다 — 편향 호출 차례에 시퀀스가 비면 ""(가드가 무편향으로 되돌림).
    rec._transcribe_window = lambda window_bytes, language, context="": seq.pop(0) if seq else ""
    return rec


def test_stream_tick_types_agreed_prefix_after_two_ticks(monkeypatch):
    wd = _load()
    # LocalAgreement-2: 같은 결과가 연속 두 번 나와야 화면에 확정되므로 틱을 두 번 돈다.
    rec = _make_recorder(wd, monkeypatch, ["안녕", "안녕"])
    # 시끄러운 1초(끝이 시끄러워 쉼 아님 → 확정/커밋 안 됨)
    import numpy as np
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == ""               # 첫 틱: 아직 한 번뿐 → 확정 안 됨
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "안녕"            # 두 번째 틱: 두 번 같음 → 확정 표시
    assert rec.committed_text == ""          # 안 쉬었으니 커밋 안 됨
    assert rec.window_start == 0


def test_stream_tick_defers_typing_until_stop_for_hold_mode(monkeypatch):
    wd = _load()
    rec = _make_recorder(wd, monkeypatch, ["안녕", "안녕"])
    rec.defer_typing_until_stop = True
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == ""
    assert rec.typed_log == []

    rec.recording = False
    wd.Recorder._stream_tick(rec, language="Korean", allow_stopped=True)
    assert rec.last_typed == "안녕"
    assert rec.typed_log == ["안녕"]


def test_stream_tick_hold_live_waits_for_stable_text_until_release(monkeypatch):
    wd = _load()
    rec = _make_recorder(wd, monkeypatch, ["abcX", "abcY", "abcY"])
    rec.append_only_until_stop = True
    calls = []

    def type_live(old, new, append_only=False):
        calls.append((old, new, append_only))
        return wd.type_diff(old, new, _FakeKeyboard(), insert=lambda _text: None, append_only=append_only)

    rec._type = type_live
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]
    wd.Recorder._stream_tick(rec, language="English")
    assert rec.last_typed == ""

    with rec.audio_lock:
        rec.audio_frames = [loud, loud]
    wd.Recorder._stream_tick(rec, language="English")
    assert rec.last_typed == ""
    assert calls[-1] == ("", "", True)

    rec.recording = False
    wd.Recorder._stream_tick(rec, language="English", allow_stopped=True)
    assert calls[-1][2] is False
    assert rec.last_typed == "abcY"


def test_qwen_original_live_types_immediate_hypothesis_and_allows_rewrite(monkeypatch):
    wd = _load()
    rec = _make_recorder(wd, monkeypatch, ["abcX", "abcY"])
    rec.app = type("App", (), {"min_volume": 35, "asr_engine": "qwen_original"})()
    calls = []

    def type_live(old, new, append_only=False):
        calls.append((old, new, append_only))
        return wd.type_diff(old, new, _FakeKeyboard(), insert=lambda _text: None, append_only=append_only)

    rec._type = type_live
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]

    wd.Recorder._stream_tick(rec, language="English")
    assert rec.last_typed == "abcX"
    assert calls[-1] == ("", "abcX", False)

    with rec.audio_lock:
        rec.audio_frames = [loud, loud]
    wd.Recorder._stream_tick(rec, language="English")
    assert rec.last_typed == "abcY"
    assert calls[-1] == ("abcX", "abcY", False)


def test_final_tick_flushes_full_hypothesis_without_pause(monkeypatch):
    wd = _load()
    rec = _make_recorder(wd, monkeypatch, ["앞말", "앞말 뒤말"])
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]

    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == ""

    rec.recording = False
    wd.Recorder._stream_tick(rec, language="Korean", allow_stopped=True)
    assert rec.last_typed == "앞말 뒤말"
    assert rec.committed_text == "앞말 뒤말"


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
    assert rec.window_start == 0


def test_stream_tick_keeps_recent_quiet_onset_before_speech():
    wd = _load()
    rec = _make_recorder(wd, None, [""])
    rec.app = type("App", (), {"min_volume": 35})()
    rec.transcriber = type("Transcriber", (), {})()
    quiet_noise = (np.ones(16000, dtype=np.int16) * 2200).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [quiet_noise] * (wd.SPEECH_START_LOOKBACK_CHUNKS + 5)
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.typed_log == []
    assert rec.window_start == 5


def test_stream_tick_low_min_volume_allows_quiet_window():
    wd = _load()
    # 작은 말소리가 게이트를 통과하는지 확인. LA-2 라 같은 결과 두 틱 뒤 표시.
    rec = _make_recorder(wd, None, ["작게 말함", "작게 말함"])
    rec.app = type("App", (), {"min_volume": 10})()
    rec.transcriber = type("Transcriber", (), {})()
    quiet_speech = (np.ones(16000, dtype=np.int16) * 2200).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [quiet_speech]
    wd.Recorder._stream_tick(rec, language="Korean")   # 1회: 아직 확정 전
    wd.Recorder._stream_tick(rec, language="Korean")   # 2회: 두 번 같음 → 표시
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


def test_stream_tick_commits_stable_text_without_waiting_for_pause():
    wd = _load()
    import numpy as np
    rec = _make_recorder(wd, None, ["안녕하세요", "안녕하세요", "안녕하세요"])
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]   # 끝이 계속 시끄러움 → pause 아님

    wd.Recorder._stream_tick(rec, language="Korean")
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.committed_text == ""

    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "안녕하세요"
    assert rec.committed_text == "안녕하세요"
    assert rec.window_start == 1


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


def test_stream_loop_does_not_send_enter_without_text(monkeypatch):
    wd = _load()
    rec = _kbd_recorder(wd)
    rec.recording = False
    rec.finalize_on_stop = True
    rec.send_enter_on_stop = True
    monkeypatch.setattr(rec, "_stream_tick", lambda *a, **k: None)
    monkeypatch.setattr(wd.dictation_history, "add_history", lambda *_: None)
    rec._stream_loop("ko")
    assert rec.transcriber.pykeyboard.events == []


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
    rec.recording = True
    rec.finalize_on_stop = True
    rec.send_enter_on_stop = True

    class Wake:
        def __init__(self): self.calls = 0
        def wait(self, _timeout):
            self.calls += 1
            return self.calls > 1

    rec._wake = Wake()

    def tick(*_args, **kwargs):
        if not kwargs.get("allow_stopped"):
            rec.last_typed = "이미 친 말"

    monkeypatch.setattr(rec, "_stream_tick", tick)  # 마지막 틱은 새 글자 없음
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
    monkeypatch.setattr(rec, "_stream_tick", lambda *a, **k: setattr(rec, "last_typed", "끝말"))
    order = []
    monkeypatch.setattr(rec, "_send_enter", lambda settle=0.03: order.append("enter"))
    monkeypatch.setattr(wd.dictation_history, "add_history", lambda *_: order.append("history"))
    rec._stream_loop("ko")
    assert order == ["enter", "history"]  # 엔터가 기록 저장보다 먼저


def test_hold_deferred_text_is_typed_before_enter(monkeypatch):
    wd = _load()
    rec = _kbd_recorder(wd)
    rec.recording = True
    rec.finalize_on_stop = True
    rec.send_enter_on_stop = True
    rec.defer_typing_until_stop = True

    class Wake:
        def __init__(self): self.calls = 0
        def wait(self, _timeout):
            self.calls += 1
            return self.calls > 1

    rec._wake = Wake()
    order = []

    def tick(*_args, **kwargs):
        if not kwargs.get("allow_stopped"):
            rec.deferred_text = "홀드 문장"

    monkeypatch.setattr(rec, "_stream_tick", tick)
    monkeypatch.setattr(rec, "_type", lambda old, new: order.append(("type", new)) or new)
    monkeypatch.setattr(rec, "_send_enter", lambda settle=0.03: order.append("enter"))
    monkeypatch.setattr(wd.dictation_history, "add_history", lambda *_: None)
    rec._stream_loop("ko")
    assert order == [("type", "홀드 문장"), "enter"]
    assert rec.last_typed == "홀드 문장"


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


def test_type_diff_uses_delete_backward_callable():
    wd = _load()
    inserted = []
    deleted = []
    kb = _FakeKeyboard()
    result = wd.type_diff(
        "abcX",
        "abcY",
        kb,
        insert=inserted.append,
        delete_backward=lambda: deleted.append("backspace"),
    )
    assert result == "abcY"
    assert inserted == ["Y"]
    assert deleted == ["backspace"]
    assert kb.events == []


def test_type_diff_append_only_skips_rewrite_that_needs_backspace():
    wd = _load()
    inserted = []
    kb = _FakeKeyboard()
    result = wd.type_diff("abcX", "abcY", kb, insert=inserted.append, append_only=True)
    assert result == "abcX"
    assert inserted == []
    assert kb.events == []


def test_type_diff_defaults_insert_to_keyboard_type():
    wd = _load()
    typed = []

    class _KbWithType(_FakeKeyboard):
        def type(self, text):
            typed.append(text)

    wd.type_diff("", "hi", _KbWithType())
    assert typed == ["hi"]


def test_unicode_type_posts_down_and_up_per_char(monkeypatch):
    wd = _load()
    posts = []
    flag_calls = []
    monkeypatch.setattr(wd, "CGEventSetFlags", lambda ev, flags: flag_calls.append(flags))
    wd.unicode_type("hi", _post=lambda tap, ev: posts.append(ev))
    assert len(posts) == 4  # down+up for 'h', down+up for 'i'
    assert flag_calls == [0, 0, 0, 0]


def test_unicode_type_empty_posts_nothing():
    wd = _load()
    posts = []
    wd.unicode_type("", _post=lambda tap, ev: posts.append(ev))
    assert posts == []


def test_recorder_type_uses_keyboard_controller_inserter(monkeypatch):
    wd = _load()
    captured = {}

    def fake_type_diff(
        old, new, kb, allow_empty=False, insert=None, append_only=False, delete_backward=None
    ):
        captured["insert"] = insert
        captured["append_only"] = append_only
        captured["delete_backward"] = delete_backward
        return new

    monkeypatch.setattr(wd, "type_diff", fake_type_diff)
    rec = _kbd_recorder(wd)
    rec._type("", "hello")
    # The custom Quartz Unicode inserter is not reliable across focused apps.
    # Leave insert=None so type_diff uses pynput Controller.type, which uses
    # pynput's platform-specific text insertion path.
    assert captured["insert"] is None
    assert captured["append_only"] is False
    if wd.CGEventCreateKeyboardEvent is not None:
        assert captured["delete_backward"] is wd.plain_backspace


def test_recorder_type_keeps_synthetic_key_guard_after_typing(monkeypatch):
    wd = _load()
    now = [100.0]

    def fake_type_diff(
        old, new, kb, allow_empty=False, insert=None, append_only=False, delete_backward=None
    ):
        now[0] += 0.02
        return new

    monkeypatch.setattr(wd, "type_diff", fake_type_diff)
    monkeypatch.setattr(wd.time, "time", lambda: now[0])
    rec = _kbd_recorder(wd)

    rec._type("", "hello")

    assert rec.self_type_guard_until >= now[0] + 1.0


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


def test_stream_tick_corrects_misheard_term_before_typing(monkeypatch):
    wd = _load()
    import numpy as np
    rec = _make_recorder(wd, None, ["각막계양 입니다"])   # 모델이 잘못 들은 결과
    rec.session_vocab = ["각막궤양"]                       # 등록 용어
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    quiet = (np.zeros(16000, dtype=np.int16)).tobytes()   # 끝 무음 → 쉼 → 확정(전체 출력)
    with rec.audio_lock:
        rec.audio_frames = [loud, quiet]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "각막궤양 입니다"            # 타이핑 전에 교정됨


def test_stream_tick_without_session_vocab_is_unchanged(monkeypatch):
    wd = _load()
    import numpy as np
    rec = _make_recorder(wd, None, ["각막계양 입니다"])
    # session_vocab 미설정 → 교정 없이 그대로
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    quiet = (np.zeros(16000, dtype=np.int16)).tobytes()   # 끝 무음 → 쉼 → 확정(전체 출력)
    with rec.audio_lock:
        rec.audio_frames = [loud, quiet]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "각막계양 입니다"


def test_local_agreement_does_not_show_a_word_that_keeps_changing():
    wd = _load()
    import numpy as np
    # 모델이 같은 자리를 '구두'→'구두점이'로 고치는 동안엔 화면에 안 뜬다(흔들림 차단).
    rec = _make_recorder(wd, None, ["구두", "구두점이", "구두점이"])
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]   # 끝이 시끄러워 쉼 아님 → 진행 중(LA-2 적용)
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == ""       # 1틱: 처음 본 말 → 확정 안 함
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == ""       # 2틱: 직전과 다름(구두↔구두점이) → 아직 확정 안 함
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "구두점이"  # 3틱: 두 번 연속 같음 → 그제서야 확정 표시


def test_local_agreement_does_not_type_unconfirmed_front_that_may_change():
    wd = _load()
    import numpy as np

    rec = _make_recorder(wd, None, ["오늘 구두", "내일 구두", "내일 구두"])
    kb = _FakeKeyboard()
    inserted = []
    rec._type = lambda old, new, append_only=False: wd.type_diff(
        old, new, kb, insert=inserted.append, append_only=append_only
    )
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]

    wd.Recorder._stream_tick(rec, language="Korean")
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == ""
    assert inserted == []
    assert kb.events == []

    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "내일 구두"
    assert inserted == ["내일 구두"]


def test_local_agreement_never_untypes_a_confirmed_word():
    wd = _load()
    import numpy as np
    # 한번 확정(두 번 같음)된 '안녕 반갑'은 뒤가 바뀌어도 지우거나 고치지 않는다.
    rec = _make_recorder(wd, None, ["안녕 반갑", "안녕 반갑", "안녕 잘가"])
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]
    wd.Recorder._stream_tick(rec, language="Korean")   # 1틱: 아직 확정 안 함
    wd.Recorder._stream_tick(rec, language="Korean")   # 2틱: 두 번 같음 → '안녕 반갑' 확정
    assert rec.last_typed == "안녕 반갑"
    wd.Recorder._stream_tick(rec, language="Korean")   # 3틱: 뒤가 '잘가'로 바뀜
    assert rec.last_typed == "안녕 반갑"               # 확정분은 그대로(안 사라짐)


def test_live_pause_commit_does_not_backspace_rewrite_visible_text():
    wd = _load()
    import numpy as np

    rec = _make_recorder(wd, None, ["안녕 반갑", "안녕 반갑", "안녕 잘가"])
    kb = _FakeKeyboard()
    inserted = []
    rec._type = lambda old, new, append_only=False: wd.type_diff(
        old, new, kb, insert=inserted.append, append_only=append_only
    )
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    quiet = np.zeros(16000, dtype=np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]
    wd.Recorder._stream_tick(rec, language="Korean")
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "안녕 반갑"

    with rec.audio_lock:
        rec.audio_frames = [loud, quiet]
    wd.Recorder._stream_tick(rec, language="Korean")

    assert rec.last_typed == "안녕 반갑"
    assert rec.committed_text == "안녕 반갑"
    assert inserted == ["안녕 반갑"]
    assert kb.events == []
    assert rec.window_start == 2


# --- 확정 시점 context 편향(_biased_commit_hypo) ---

def _bias_recorder(wd, biased_text):
    rec = wd.Recorder.__new__(wd.Recorder)
    rec.session_vocab = ["커밋", "푸시"]
    rec.app = type("App", (), {"domain_context": ""})()
    # 편향 호출(context 있음)일 때만 지정 텍스트를, 라이브 호출(context 없음)이면 "" 반환
    rec._transcribe_window = (
        lambda window, language, context="": biased_text if context else ""
    )
    return rec


def test_biased_commit_accepts_when_guard_passes():
    wd = _load()
    rec = _bias_recorder(wd, "커밋하고 푸시해")
    out = wd.Recorder._biased_commit_hypo(
        rec, b"x", "Korean", unbiased="거미 타고 부시해", window_secs=2.0
    )
    assert out == "커밋하고 푸시해"   # 가드 통과 → 편향본 채택


def test_biased_commit_rejects_leak():
    wd = _load()
    rec = _bias_recorder(wd, "커밋 오늘 날씨 좋다")
    out = wd.Recorder._biased_commit_hypo(
        rec, b"x", "Korean", unbiased="오늘 날씨 좋다", window_secs=2.0
    )
    assert out == "오늘 날씨 좋다"   # 근거 없는 '커밋' → 누출 → 무편향 유지


def test_biased_commit_skips_short_window():
    wd = _load()
    called = {"n": 0}
    rec = wd.Recorder.__new__(wd.Recorder)
    rec.session_vocab = ["커밋"]
    rec.app = type("App", (), {"domain_context": ""})()
    rec._transcribe_window = lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "커밋"
    out = wd.Recorder._biased_commit_hypo(rec, b"x", "Korean", unbiased="거미", window_secs=0.4)
    assert out == "거미"        # 짧은 창(증거 약함) → 편향 안 함
    assert called["n"] == 0     # 모델 재호출조차 안 함


def test_biased_commit_skips_without_vocab():
    wd = _load()
    rec = wd.Recorder.__new__(wd.Recorder)
    rec.session_vocab = []
    rec.app = type("App", (), {"domain_context": ""})()
    rec._transcribe_window = lambda *a, **k: "커밋"
    out = wd.Recorder._biased_commit_hypo(rec, b"x", "Korean", unbiased="거미", window_secs=2.0)
    assert out == "거미"        # 등록어 없음 → 편향 안 함


def test_biased_commit_rejects_label_echo():
    wd = _load()
    rec = _bias_recorder(wd, "전문 용어: 커밋, 푸시")
    out = wd.Recorder._biased_commit_hypo(
        rec, b"x", "Korean", unbiased="거미 타고", window_secs=2.0
    )
    assert out == "거미 타고"   # context 머리표가 새어나옴 → 거부


def test_stream_tick_commit_biases_registered_term(monkeypatch):
    wd = _load()
    import numpy as np
    # 라이브(무편향)는 '거미 타고 부시해'로 잘못 듣고, 확정 편향은 '커밋하고 푸시해'로 고침.
    rec = _make_recorder(wd, monkeypatch, ["거미 타고 부시해"])
    rec.session_vocab = ["커밋", "푸시"]
    rec._transcribe_window = (
        lambda window, language, context="": "커밋하고 푸시해" if context else "거미 타고 부시해"
    )
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    quiet = (np.zeros(16000, dtype=np.int16)).tobytes()  # 끝 무음 → 쉼 → 확정
    with rec.audio_lock:
        rec.audio_frames = [loud, quiet]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.committed_text == "커밋하고 푸시해"   # 확정본이 편향으로 교정됨
    assert rec.last_typed == "커밋하고 푸시해"


def test_stream_tick_commit_keeps_unbiased_on_leak(monkeypatch):
    wd = _load()
    import numpy as np
    rec = _make_recorder(wd, monkeypatch, ["오늘 날씨 좋다"])
    rec.session_vocab = ["커밋"]
    # 편향이 근거 없는 '커밋'을 앞에 흘림 → 가드가 거부 → 무편향 유지
    rec._transcribe_window = (
        lambda window, language, context="": "커밋 오늘 날씨 좋다" if context else "오늘 날씨 좋다"
    )
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    quiet = (np.zeros(16000, dtype=np.int16)).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud, quiet]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.committed_text == "오늘 날씨 좋다"   # 누출 거부 → 무편향 확정


def test_stream_tick_holds_previous_when_live_chunk_is_foreign():
    wd = _load()
    import numpy as np
    # 말하는 도중 토막이 외국어(러시아어)로 샘 → 화면에 안 띄우고 직전 한국어 유지
    rec = _make_recorder(wd, None, ["Привет мир"])
    rec.committed_text = "이전 한국어"
    rec.last_typed = "이전 한국어"
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()  # 끝 시끄러움 → 커밋 아님
    with rec.audio_lock:
        rec.audio_frames = [loud]
    wd.Recorder._stream_tick(rec, language="auto")
    assert rec.last_typed == "이전 한국어"            # 외국어 토막 안 뜨고 직전 유지
    assert "Привет" not in "".join(rec.typed_log)    # 외국어가 한 번도 타이핑 안 됨


def test_stream_tick_redoes_in_korean_when_commit_is_foreign():
    wd = _load()
    import numpy as np
    # auto 받아쓰기가 외국어(중국어)로 샜지만, 한국어 강제 재받아쓰기는 제대로 들림
    rec = _make_recorder(wd, None, [])
    rec.session_vocab = []
    rec._transcribe_window = (
        lambda window, language, context="": "안녕하세요" if language == "Korean" else "你好世界"
    )
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    quiet = (np.zeros(16000, dtype=np.int16)).tobytes()   # 끝 무음 → 쉼 → 확정
    with rec.audio_lock:
        rec.audio_frames = [loud, quiet]
    wd.Recorder._stream_tick(rec, language="auto")
    assert rec.committed_text == "안녕하세요"            # 외국어 확정 대신 한국어로 다시
    assert "你" not in "".join(rec.typed_log)            # 중국어가 확정/타이핑되지 않음
