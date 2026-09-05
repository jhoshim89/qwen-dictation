import os


ASR_ENGINE_QWEN = "qwen"
ASR_ENGINE_QWEN_ORIGINAL = "qwen_original"
ASR_ENGINE_QWEN_MLX = "qwen_mlx"
ASR_ENGINE_NEMOTRON_MLX = "nemotron_mlx"
DEFAULT_ASR_ENGINE = ASR_ENGINE_QWEN

QWEN_MODEL_ID = os.environ.get("QWEN_ASR_1_7B_PATH", "Qwen/Qwen3-ASR-1.7B")
# 같은 Qwen3-ASR 1.7B 가중치를 Apple Silicon MLX 8bit 로 변환한 것. 실측(M-시리즈,
# 한국어 9초 문장): 로드 12초→3초, 첫 추론 12초→1.5초, 정상 추론 0.16초→0.10초,
# 받아쓰기 결과는 동일. 0.6B 는 "안압"→"아나본" 같은 오인이 있어 채택하지 않는다.
QWEN_MLX_MODEL_ID = os.environ.get("QWEN_ASR_MLX_PATH", "mlx-community/Qwen3-ASR-1.7B-8bit")
NEMOTRON_MLX_MODEL_ID = os.environ.get(
    "NEMOTRON_ASR_MLX_PATH",
    "mlx-community/nemotron-3.5-asr-streaming-0.6b",
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
    ASR_ENGINE_QWEN_MLX: {
        "id": ASR_ENGINE_QWEN_MLX,
        "label": "Qwen3-ASR 1.7B (MLX)",
        "short_label": "Qwen MLX",
        "detail": "Apple Silicon MLX 8bit, context bias",
        "model": QWEN_MLX_MODEL_ID,
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
    "qwen_mlx": ASR_ENGINE_QWEN_MLX,
    "qwen3_mlx": ASR_ENGINE_QWEN_MLX,
    "qwen_mlx_8bit": ASR_ENGINE_QWEN_MLX,
    "mlx": ASR_ENGINE_QWEN_MLX,
    "nemotron": ASR_ENGINE_NEMOTRON_MLX,
    "nemotron_mlx": ASR_ENGINE_NEMOTRON_MLX,
    "nemotron_3_5": ASR_ENGINE_NEMOTRON_MLX,
    "nemotron_3_5_asr": ASR_ENGINE_NEMOTRON_MLX,
    "nemo": ASR_ENGINE_NEMOTRON_MLX,
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
            ASR_ENGINE_QWEN_MLX,
            ASR_ENGINE_QWEN_ORIGINAL,
            ASR_ENGINE_NEMOTRON_MLX,
        )
    ]


def is_mlx_engine(engine):
    engine = normalize_asr_engine(engine)
    return engine in (ASR_ENGINE_QWEN_MLX, ASR_ENGINE_NEMOTRON_MLX)


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
