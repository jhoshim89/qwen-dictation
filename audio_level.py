# audio_level.py
"""마이크 음량(RMS)을 0.0~1.0 으로 측정하고 작은 파일로 주고받는 헬퍼.

녹음 프로세스가 write_level() 로 현재 음량을 쓰고,
HUD 프로세스가 read_level() 로 읽어 막대를 그린다.
"""
import os
import tempfile

import numpy as np

# 16-bit PCM 최대 진폭. 사람이 보통 말할 때의 RMS를 막대가 꽉 차게 보이도록
# 전체 범위(32768)가 아니라 더 낮은 기준으로 정규화한다.
_FULL_SCALE = 32768.0
_NORMALIZE_REF = 3000.0  # 이 RMS 정도면 막대가 가득 찬다(체감 보정값)


def level_file_path():
    return os.path.join(tempfile.gettempdir(), "qwen_dictation_level")


def compute_rms(pcm_bytes):
    """리틀엔디언 16-bit mono PCM 바이트 -> 0.0~1.0 정규화 음량."""
    if not pcm_bytes:
        return 0.0
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(samples ** 2)))
    level = rms / _NORMALIZE_REF
    if level < 0.0:
        return 0.0
    if level > 1.0:
        return 1.0
    return level


def write_level(level):
    try:
        with open(level_file_path(), "w") as f:
            f.write(f"{float(level):.4f}")
    except Exception:
        pass


def read_level():
    try:
        with open(level_file_path(), "r") as f:
            return float(f.read().strip() or 0.0)
    except Exception:
        return 0.0


def clear_level():
    try:
        os.remove(level_file_path())
    except Exception:
        pass
