import importlib.util

import pytest

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


def test_looks_like_foreign_language():
    wd = _load()
    # 한글/영어/혼합/숫자·기호 → 외국어 아님(진짜 발화로 본다)
    assert wd.looks_like_foreign_language("녹내장 안압 측정") is False
    assert wd.looks_like_foreign_language("commit and push") is False
    assert wd.looks_like_foreign_language("이거 commit 해줘") is False
    assert wd.looks_like_foreign_language("") is False
    assert wd.looks_like_foreign_language("123 mmHg 95%.") is False
    # 한글·영어가 한 글자도 없고 전부 외국 문자 → 외국어
    assert wd.looks_like_foreign_language("你好世界") is True        # 중국어
    assert wd.looks_like_foreign_language("こんにちは") is True       # 일본어
    assert wd.looks_like_foreign_language("Привет мир") is True      # 러시아어
    assert wd.looks_like_foreign_language("สวัสดีครับ") is True      # 태국어


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


def test_looks_like_context_label_echo():
    wd = _load()
    # context 머리표가 출력에 들어오면 echo (사용자가 말하는 내용이 아님)
    assert wd.looks_like_context_label_echo("전문 용어: 녹내장, 안압") is True
    assert wd.looks_like_context_label_echo("전문 용어: 아무거나 지어낸 말") is True
    # 실제 발화엔 머리표가 없다
    assert wd.looks_like_context_label_echo("녹내장 환자를 봤어요") is False
    assert wd.looks_like_context_label_echo("") is False


def test_transcribe_passes_no_context(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["각막", "궤양"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(1).randn(16000) * 5000))

    tr = wd.SpeechTranscriber("cpu", None)
    tr.domain_context = "수의안과 진료"
    fake = _FakeModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)

    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "녹음 결과"
    assert fake.calls[0]["context"] == ""   # 용어/분야를 모델에 주지 않는다(누출 0)


def test_transcribe_file_forwards_context(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["커밋"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(2).randn(16000) * 5000))

    tr = wd.SpeechTranscriber("cpu", None)
    fake = _FakeModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)

    out = tr.transcribe_file(str(wav), language="Korean", context="전문 용어: 커밋")
    assert out == "녹음 결과"
    assert fake.calls[0]["context"] == "전문 용어: 커밋"  # 확정 시점엔 context 를 모델에 넘긴다


def test_transcribe_file_uses_nemotron_mlx_stream_generate(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(4).randn(16000) * 5000))

    class FakeNemotron:
        def __init__(self):
            self.calls = []

        def generate(self, audio, language=None, **kw):
            raise AssertionError("Nemotron native path must use stream_generate")

        def stream_generate(self, audio, language=None, **kw):
            self.calls.append({"audio": audio, "language": language, "kw": kw})
            yield type("Result", (), {"text": "네모트론 중간"})()
            yield type("Result", (), {"text": "네모트론 결과"})()

    fake = FakeNemotron()
    tr = wd.SpeechTranscriber("cpu", None, asr_engine="nemotron")
    monkeypatch.setattr(tr, "get_nemotron_model", lambda: fake)
    # mlx 는 선택 설치 런타임이다. 없는 환경에서도 이 경로의 로직을 검증할 수 있게
    # `mlx.core.array` 만 흉내 낸다(실제 배열 변환은 이 테스트의 관심사가 아니다).
    import sys
    import types
    fake_mx = types.ModuleType("mlx.core")
    fake_mx.array = lambda samples: samples
    fake_mlx = types.ModuleType("mlx")
    fake_mlx.core = fake_mx
    monkeypatch.setitem(sys.modules, "mlx", fake_mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", fake_mx)

    out = tr.transcribe_file(str(wav), language="ko", context="전문 용어: 커밋")
    assert out == "네모트론 결과"
    assert fake.calls[0]["language"] == "ko-KR"
    assert not isinstance(fake.calls[0]["audio"], str)
    assert "context" not in fake.calls[0]["kw"]


def test_biased_commit_skips_context_for_nemotron(monkeypatch):
    wd = _load()
    rec = wd.Recorder.__new__(wd.Recorder)
    rec.transcriber = type("Transcriber", (), {"asr_engine": "nemotron_mlx"})()
    rec.session_vocab = ["커밋"]
    rec.app = type("App", (), {"domain_context": "개발"})()
    called = []
    rec._transcribe_window = lambda *a, **k: called.append((a, k)) or "biased"

    assert wd.Recorder._biased_commit_hypo(rec, b"1234", "Korean", "커밋", 2.0) == "커밋"
    assert called == []


# --- 모델 로딩 표시(HUD '불러오는 중') ---

def test_model_loading_reflects_transcriber_flag():
    import types
    wd = _load()
    tr = types.SimpleNamespace(loading=False)
    app = types.SimpleNamespace(recorder=types.SimpleNamespace(transcriber=tr))
    assert wd.StatusBarApp._model_loading(app) is False
    tr.loading = True
    assert wd.StatusBarApp._model_loading(app) is True


def test_model_loading_reflects_queued_background_load():
    import types
    wd = _load()
    tr = types.SimpleNamespace(loading=False, current_model_loading=lambda: True)
    app = types.SimpleNamespace(recorder=types.SimpleNamespace(transcriber=tr))
    assert wd.StatusBarApp._model_loading(app) is True


def test_model_loading_false_without_recorder():
    import types
    wd = _load()
    app = types.SimpleNamespace(recorder=None)
    assert wd.StatusBarApp._model_loading(app) is False


def test_started_overlay_shows_listening_not_cold_start(monkeypatch):
    import types
    wd = _load()
    labels, updates = [], []
    ov = types.SimpleNamespace(
        set_mode=lambda *args: None,
        update=lambda level, elapsed: updates.append((level, elapsed)),
        set_processing=lambda flag: None, show_status=labels.append, hide=lambda: None,
    )
    rec = types.SimpleNamespace(transcriber=types.SimpleNamespace(loading=False))
    app = types.SimpleNamespace(
        recorder=rec, hud_mode="pill", hud_pin_x=None, hud_pin_y=None, started=True,
        start_time=100.0, elapsed_time=0, title=None, processing_active=False, _applied_hud=None,
    )
    app._model_loading = wd.StatusBarApp._model_loading.__get__(app, type(app))
    monkeypatch.setattr(wd.hud_overlay, "get_overlay", lambda: ov)
    monkeypatch.setattr(wd.audio_level, "read_level", lambda: 0.42)
    monkeypatch.setattr(wd.time, "time", lambda: 102.0)

    wd.StatusBarApp._tick_overlay(app, None)

    assert (labels, updates) == (["듣는 중"], [(0.42, 2)])


def test_started_overlay_waits_for_first_microphone_frame(monkeypatch):
    import types
    wd = _load()
    labels, updates = [], []
    ov = types.SimpleNamespace(
        set_mode=lambda *args: None,
        update=lambda level, elapsed: updates.append((level, elapsed)),
        set_processing=lambda flag: None,
        show_status=labels.append,
        hide=lambda: None,
    )
    rec = types.SimpleNamespace(
        transcriber=types.SimpleNamespace(loading=False),
        capture_ready=lambda: False,
    )
    app = types.SimpleNamespace(
        recorder=rec, hud_mode="pill", hud_pin_x=None, hud_pin_y=None, started=True,
        start_time=100.0, elapsed_time=0, title=None, processing_active=False, _applied_hud=None,
    )
    app._model_loading = wd.StatusBarApp._model_loading.__get__(app, type(app))
    monkeypatch.setattr(wd.hud_overlay, "get_overlay", lambda: ov)
    monkeypatch.setattr(wd.time, "time", lambda: 101.0)

    wd.StatusBarApp._tick_overlay(app, None)

    assert (labels, updates) == (["마이크 준비 중…"], [(0.0, 1)])


def test_loading_pulse_in_unit_range():
    wd = _load()
    for _ in range(20):
        v = wd.StatusBarApp._loading_pulse()
        assert 0.0 <= v <= 1.0


def test_get_model_clears_loading_flag_on_success(monkeypatch):
    import types
    wd = _load()
    tr = wd.SpeechTranscriber("cpu", None)

    class FakeModel:
        def __init__(self):
            self.model = types.SimpleNamespace(to=lambda dev: None)

        @classmethod
        def from_pretrained(cls, name, dtype=None):
            assert tr.loading is True   # 로드가 진행되는 동안엔 플래그가 켜져 있어야 한다
            return cls()

    monkeypatch.setattr(wd, "Qwen3ASRModel", FakeModel)
    monkeypatch.setattr(wd, "safe_notify", lambda *a, **k: None)
    tr.get_model()
    assert tr.loading is False           # 끝나면 내려간다
    assert tr.model_1_7b is not None
    assert tr.current_model_ready() is True


def test_get_model_clears_loading_flag_on_failure(monkeypatch):
    import pytest
    wd = _load()
    tr = wd.SpeechTranscriber("cpu", None)

    class BoomModel:
        @classmethod
        def from_pretrained(cls, name, dtype=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(wd, "Qwen3ASRModel", BoomModel)
    monkeypatch.setattr(wd, "safe_notify", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        tr.get_model()
    assert tr.loading is False           # 실패해도 표시가 영원히 남지 않게 내려간다
    assert tr.current_model_ready() is False
    with pytest.raises(RuntimeError, match="ASR model load failed"):
        tr.wait_current_model_ready(timeout=0.2)


def test_get_model_warms_up_before_ready(monkeypatch):
    # MPS 첫 추론은 컴파일 때문에 10초 안팎 걸린다. 준비 완료로 표시하기 전에 합성
    # 오디오로 예열해 첫 실제 받아쓰기가 다음 틱과 같은 속도로 나오게 한다.
    import os
    import types
    wd = _load()
    tr = wd.SpeechTranscriber("cpu", None)
    calls = []

    class FakeModel:
        def __init__(self):
            self.model = types.SimpleNamespace(to=lambda dev: None)

        @classmethod
        def from_pretrained(cls, name, dtype=None):
            return cls()

        def transcribe(self, path, context="", language=None):
            assert tr.current_model_ready() is False   # 예열은 준비 표시 전에 돈다
            assert tr.loading is True                  # 예열 중에도 HUD 는 '불러오는 중'
            assert os.path.exists(path) and path.endswith(".wav")
            calls.append((os.path.getsize(path), context))
            return []

    monkeypatch.setattr(wd, "Qwen3ASRModel", FakeModel)
    monkeypatch.setattr(wd, "safe_notify", lambda *a, **k: None)
    tr.get_model()
    assert len(calls) == len(wd.WARMUP_WINDOW_SECS)
    assert all(context == "" for _, context in calls)   # 등록 용어를 예열에 쓰지 않는다
    assert calls[0][0] < calls[1][0]                    # 짧은 창, 긴 창 순서
    assert tr.current_model_ready() is True


def test_get_model_survives_warm_up_failure(monkeypatch):
    import types
    wd = _load()
    tr = wd.SpeechTranscriber("cpu", None)

    class FakeModel:
        def __init__(self):
            self.model = types.SimpleNamespace(to=lambda dev: None)

        @classmethod
        def from_pretrained(cls, name, dtype=None):
            return cls()

        def transcribe(self, path, context="", language=None):
            raise RuntimeError("warm-up boom")

    monkeypatch.setattr(wd, "Qwen3ASRModel", FakeModel)
    monkeypatch.setattr(wd, "safe_notify", lambda *a, **k: None)
    tr.get_model()                                       # 예열 실패는 로드 실패가 아니다
    assert tr.current_model_ready() is True
    assert tr.loading is False


def test_warmup_audio_is_deterministic_and_bounded():
    wd = _load()
    a = wd.warmup_audio(1.6)
    b = wd.warmup_audio(1.6)
    assert a.shape == (int(1.6 * 16000),)
    assert (a == b).all()
    assert float(abs(a).max()) < 0.2                    # 조용하지만 무음 게이트보다는 큼


def _fake_mlx_qwen(calls):
    class FakeMlxQwen:
        def generate(self, audio, **kw):
            calls.append({"audio": audio, "kw": kw})
            return type("Out", (), {"text": " 엠엘엑스 결과 "})()
    return FakeMlxQwen()


def test_qwen_mlx_transcribe_maps_context_to_system_prompt(tmp_path, monkeypatch):
    # qwen-asr 는 context 를 system 메시지로 넣는다. MLX 경로도 같은 자리(system_prompt)
    # 에 넣어야 확정 시점 편향이 torch 엔진과 같은 방식으로 동작한다.
    import numpy as np
    wd = _load()
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(4).randn(16000) * 5000))
    calls = []
    tr = wd.SpeechTranscriber("cpu", None, asr_engine="qwen_mlx")
    monkeypatch.setattr(tr, "get_qwen_mlx_model", lambda: _fake_mlx_qwen(calls))

    out = tr.transcribe_file(str(wav), language="ko", context="전문 용어: 각막")
    assert out == "엠엘엑스 결과"
    assert calls[0]["kw"]["language"] == "Korean"
    assert calls[0]["kw"]["system_prompt"] == "전문 용어: 각막"

    calls.clear()
    tr.transcribe_file(str(wav), language="auto", context="")
    assert calls[0]["kw"]["language"] is None          # auto → 언어 자동 감지
    assert calls[0]["kw"]["system_prompt"] is None     # 빈 context 는 system 없이


def test_qwen_mlx_model_loads_and_warms_up_before_ready(monkeypatch):
    wd = _load()
    tr = wd.SpeechTranscriber("cpu", None, asr_engine="qwen_mlx")
    calls = []
    fake = _fake_mlx_qwen(calls)
    loaded = []

    def fake_load(model_id):
        assert tr.loading is True
        loaded.append(model_id)
        return fake

    monkeypatch.setattr(wd, "load_mlx_stt_model", fake_load)
    monkeypatch.setattr(wd, "safe_notify", lambda *a, **k: None)
    assert tr.current_model_ready() is False
    assert tr.get_qwen_mlx_model() is fake
    assert loaded == [wd.QWEN_MLX_MODEL]
    assert len(calls) == len(wd.WARMUP_WINDOW_SECS)   # 예열이 돌았다
    assert tr.current_model_ready() is True
    assert tr.loading is False
    assert tr.get_qwen_mlx_model() is fake            # 두 번째는 재로드 없음
    assert loaded == [wd.QWEN_MLX_MODEL]


def test_qwen_mlx_missing_runtime_gives_install_hint(monkeypatch):
    import builtins
    import pytest
    wd = _load()
    real_import = builtins.__import__

    def no_mlx(name, *a, **k):
        if name.startswith("mlx_audio"):
            raise ImportError("no mlx_audio")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_mlx)
    with pytest.raises(RuntimeError, match="install_mlx_runtime"):
        wd.load_mlx_stt_model("mlx-community/anything")


def test_ensure_loading_routes_qwen_mlx(monkeypatch):
    wd = _load()
    tr = wd.SpeechTranscriber("cpu", None, asr_engine="qwen_mlx")
    called = []
    monkeypatch.setattr(tr, "get_qwen_mlx_model", lambda: called.append("mlx"))
    monkeypatch.setattr(tr, "get_model", lambda: called.append("torch"))
    tr.ensure_current_model_loading()
    tr._model_state_changed.wait(2.0)
    import time
    for _ in range(50):
        if called:
            break
        time.sleep(0.02)
    assert called == ["mlx"]
