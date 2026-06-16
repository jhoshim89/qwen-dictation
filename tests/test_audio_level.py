# test_audio_level.py
import os
import struct
import app_paths
import audio_level


def test_level_file_path_under_tmp_or_userdir():
    p = audio_level.level_file_path()
    assert p.endswith("qwen_dictation_level")


def test_compute_rms_silence_is_zero():
    silence = struct.pack("<" + "h" * 1024, *([0] * 1024))
    assert audio_level.compute_rms(silence) == 0.0


def test_compute_rms_loud_is_positive_and_capped():
    loud = struct.pack("<" + "h" * 1024, *([20000] * 1024))
    v = audio_level.compute_rms(loud)
    assert 0.0 < v <= 1.0


def test_write_then_read_level_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_level, "level_file_path", lambda: str(tmp_path / "lvl"))
    audio_level.write_level(0.42)
    assert abs(audio_level.read_level() - 0.42) < 0.01


def test_read_level_missing_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_level, "level_file_path", lambda: str(tmp_path / "nope"))
    assert audio_level.read_level() == 0.0
