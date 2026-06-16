import asr_engines


def test_normalize_asr_engine_aliases():
    assert asr_engines.normalize_asr_engine("qwen") == "qwen"
    assert asr_engines.normalize_asr_engine("QN") == "qwen"
    assert asr_engines.normalize_asr_engine("qwen-original") == "qwen_original"
    assert asr_engines.normalize_asr_engine("nemotron") == "nemotron_mlx"
    assert asr_engines.normalize_asr_engine("nemotron-mlx") == "nemotron_mlx"
    assert asr_engines.normalize_asr_engine("unknown") == "qwen"


def test_engine_metadata_marks_context_support():
    assert asr_engines.asr_engine_supports_context("qwen") is True
    assert asr_engines.asr_engine_supports_context("qwen_original") is True
    assert asr_engines.asr_engine_supports_context("nemotron") is False
    ids = [item["id"] for item in asr_engines.available_asr_engines()]
    assert ids == ["qwen", "qwen_original", "nemotron_mlx"]


def test_removed_engine_aliases_fall_back_to_default():
    assert asr_engines.normalize_asr_engine("google") == "qwen"
    assert asr_engines.normalize_asr_engine("speech-to-text") == "qwen"
    assert asr_engines.normalize_asr_engine("sherpa") == "qwen"
    assert asr_engines.normalize_asr_engine("zipformer-ko") == "qwen"


def test_language_mapping_for_each_engine():
    assert asr_engines.normalize_qwen_language("ko") == "Korean"
    assert asr_engines.normalize_qwen_language("auto") is None
    assert asr_engines.normalize_nemotron_language("ko") == "ko-KR"
    assert asr_engines.normalize_nemotron_language("English") == "en-US"
    assert asr_engines.normalize_nemotron_language("auto") == "auto"
