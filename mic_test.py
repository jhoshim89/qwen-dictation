#!/usr/bin/env python3
"""마이크 입력이 실제로 들어오는지 확인하는 진단 도구.

사용법: ./venv/bin/python mic_test.py [녹음초]
녹음하는 동안 말을 하세요. peak/rms 가 크면 마이크 캡처 정상,
peak 가 0/아주 작으면 마이크 권한 또는 입력 장치 문제.
"""
import sys
import numpy as np
import pyaudio

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
RATE = 16000
CHUNK = 1024

pa = pyaudio.PyAudio()
try:
    default_in = pa.get_default_input_device_info()
    print(f"기본 입력 장치: {default_in.get('name')!r} (index {default_in.get('index')})")
except Exception as e:
    print(f"기본 입력 장치 조회 실패: {e}")

stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)
print(f"{seconds:.0f}초 녹음 시작 — 지금 말하세요...")
frames = []
for _ in range(int(RATE / CHUNK * seconds)):
    frames.append(stream.read(CHUNK, exception_on_overflow=False))
stream.stop_stream(); stream.close(); pa.terminate()

data = np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32)
peak = float(np.max(np.abs(data))) if len(data) else 0.0
rms = float(np.sqrt(np.mean(data ** 2))) if len(data) else 0.0
print(f"결과: peak={peak:.0f} rms={rms:.0f} (int16 최대 32767)")
if peak < 100:
    print("판정: 입력이 거의 0 → 마이크 권한 없음/입력 장치 문제 (말해도 0이면 권한 문제)")
elif peak < 1000:
    print("판정: 주변음만 잡힘(말 안 했거나 마이크 멀거나)")
else:
    print("판정: 마이크 캡처 정상 ✅")
