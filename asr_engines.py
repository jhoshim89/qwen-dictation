import os


ASR_ENGINE_QWEN = "qwen"
ASR_ENGINE_QWEN_ORIGINAL = "qwen_original"
ASR_ENGINE_NEMOTRON_MLX = "nemotron_mlx"
ASR_ENGINE_GOOGLE_STT = "google_stt"
ASR_ENGINE_SHERPA_ONNX_KO = "sherpa_onnx_ko"
DEFAULT_ASR_ENGINE = ASR_ENGINE_QWEN

QWEN_MODEL_ID = os.environ.get("QWEN_ASR_1_7B_PATH", "Qwen/Qwen3-ASR-1.7B")
NEMOTRON_MLX_MODEL_ID = os.environ.get(
    "NEMOTRON_ASR_MLX_PATH",
    "mlx-community/nemotron-3.5-asr-streaming-0.6b",
)
GOOGLE_STT_MODEL_ID = os.environ.get("GOOGLE_STT_MODEL", "latest_long")
SHERPA_ONNX_KO_MODEL_ID = os.environ.get(
    "SHERPA_ONNX_KO_MODEL",
    "k2-fsa/sherpa-onnx-streaming-zipformer-korean-2024-06-16",
)


ENGINE_DEFINITIONS = {
    ASR_ENGINE_QWEN: {
        "id": ASR_ENGINE_QWEN,
        "label": "Qwen3-ASR 1.7B",
        "short_label": "Qwen",
        "detail": "context bias",
        "model": QWEN_MODEL_ID,
        "supports_context": True,
    },
    ASR_ENGINE_QWEN_ORIGINAL: {
        "id": ASR_ENGINE_QWEN_ORIGINAL,
        "label": "Qwen3-ASR 1.7B Original",
        "short_label": "Qwen Original",
        "detail": "rolling WAV transcribe",
        "model": QWEN_MODEL_ID,
        "supports_context": True,
    },
    ASR_ENGINE_NEMOTRON_MLX: {
        "id": ASR_ENGINE_NEMOTRON_MLX,
        "label": "Nemotron 3.5 ASR 0.6B (MLX)",
        "short_label": "Nemotron",
        "detail": "Apple Silicon MLX",
        "model": NEMOTRON_MLX_MODEL_ID,
        "supports_context": False,
    },
    ASR_ENGINE_GOOGLE_STT: {
        "id": ASR_ENGINE_GOOGLE_STT,
        "label": "Google Speech-to-Text",
        "short_label": "Google",
        "detail": "cloud",
        "model": GOOGLE_STT_MODEL_ID,
        "supports_context": False,
        "requires_network": True,
        "requires_credentials": True,
        "local": False,
    },
    ASR_ENGINE_SHERPA_ONNX_KO: {
        "id": ASR_ENGINE_SHERPA_ONNX_KO,
        "label": "sherpa-onnx Korean Zipformer",
        "short_label": "sherpa",
        "detail": "local Korean",
        "model": SHERPA_ONNX_KO_MODEL_ID,
        "supports_context": False,
        "requires_network": False,
        "requires_credentials": False,
        "local": True,
    },
}

_ENGINE_ALIASES = {
    "qwen": ASR_ENGINE_QWEN,
    "qwen3": ASR_ENGINE_QWEN,
    "qwen3_asr": ASR_ENGINE_QWEN,
    "qwen_1_7b": ASR_ENGINE_QWEN,
    "qn": ASR_ENGINE_QWEN,
    "qwen_original": ASR_ENGINE_QWEN_ORIGINAL,
    "qwen_orig": ASR_ENGINE_QWEN_ORIGINAL,
    "qwen_rolling": ASR_ENGINE_QWEN_ORIGINAL,
    "qwen_windowed": ASR_ENGINE_QWEN_ORIGINAL,
    "nemotron": ASR_ENGINE_NEMOTRON_MLX,
    "nemotron_mlx": ASR_ENGINE_NEMOTRON_MLX,
    "nemotron_3_5": ASR_ENGINE_NEMOTRON_MLX,
    "nemotron_3_5_asr": ASR_ENGINE_NEMOTRON_MLX,
    "nemo": ASR_ENGINE_NEMOTRON_MLX,
    "google": ASR_ENGINE_GOOGLE_STT,
    "google_stt": ASR_ENGINE_GOOGLE_STT,
    "gcp": ASR_ENGINE_GOOGLE_STT,
    "speech_to_text": ASR_ENGINE_GOOGLE_STT,
    "sherpa": ASR_ENGINE_SHERPA_ONNX_KO,
    "sherpa_onnx": ASR_ENGINE_SHERPA_ONNX_KO,
    "sherpa_onnx_ko": ASR_ENGINE_SHERPA_ONNX_KO,
    "zipformer_ko": ASR_ENGINE_SHERPA_ONNX_KO,
}

QWEN_LANGUAGE_MAP = {
    "auto": None,
    "ko": "Korean",
    "kr": "Korean",
    "korean": "Korean",
    "en": "English",
    "english": "English",
    "zh": "Chinese",
    "chinese": "Chinese",
    "ja": "Japanese",
    "jp": "Japanese",
    "japanese": "Japanese",
}

NEMOTRON_LANGUAGE_MAP = {
    "auto": "auto",
    "ko": "ko-KR",
    "kr": "ko-KR",
    "korean": "ko-KR",
    "en": "en-US",
    "english": "en-US",
    "zh": "zh-CN",
    "chinese": "zh-CN",
    "ja": "ja-JP",
    "jp": "ja-JP",
    "japanese": "ja-JP",
}

GOOGLE_LANGUAGE_MAP = {
    "auto": "ko-KR",
    "ko": "ko-KR",
    "kr": "ko-KR",
    "korean": "ko-KR",
    "en": "en-US",
    "english": "en-US",
    "zh": "zh-CN",
    "chinese": "zh-CN",
    "ja": "ja-JP",
    "jp": "ja-JP",
    "japanese": "ja-JP",
}


def normalize_asr_engine(value):
    key = str(value or "").strip().lower().replace("-", "_")
    return _ENGINE_ALIASES.get(key, DEFAULT_ASR_ENGINE)


def asr_engine_label(engine):
    engine = normalize_asr_engine(engine)
    return ENGINE_DEFINITIONS[engine]["label"]


def asr_engine_model(engine):
    engine = normalize_asr_engine(engine)
    return ENGINE_DEFINITIONS[engine]["model"]


def asr_engine_supports_context(engine):
    engine = normalize_asr_engine(engine)
    return bool(ENGINE_DEFINITIONS[engine]["supports_context"])


def available_asr_engines():
    return [
        dict(ENGINE_DEFINITIONS[key])
        for key in (
            ASR_ENGINE_QWEN,
            ASR_ENGINE_QWEN_ORIGINAL,
            ASR_ENGINE_NEMOTRON_MLX,
            ASR_ENGINE_GOOGLE_STT,
            ASR_ENGINE_SHERPA_ONNX_KO,
        )
    ]


def normalize_qwen_language(language):
    if not language:
        return None
    if isinstance(language, list):
        language = language[0] if language else None
    language = str(language).strip()
    if not language:
        return None
    return QWEN_LANGUAGE_MAP.get(language.lower(), language)


def normalize_nemotron_language(language):
    if not language:
        return "auto"
    if isinstance(language, list):
        language = language[0] if language else None
    language = str(language).strip()
    if not language:
        return "auto"
    return NEMOTRON_LANGUAGE_MAP.get(language.lower(), language)


def normalize_google_language(language):
    if not language:
        return "ko-KR"
    if isinstance(language, list):
        language = language[0] if language else None
    language = str(language).strip()
    if not language:
        return "ko-KR"
    return GOOGLE_LANGUAGE_MAP.get(language.lower(), language)
