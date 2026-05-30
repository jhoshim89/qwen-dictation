# setup.py
"""py2app 빌드 설정.

빌드:   ./venv/bin/python setup.py py2app
산출물: dist/Qwen Dictation.app

모델 가중치(1.8GB)는 번들에 넣지 않는다. 앱은 실행 시 ~/.cache/huggingface 의
기존 Qwen3-ASR 캐시를 그대로 참조한다.
"""
import sys

from setuptools import setup

# py2app 의 modulegraph 가 torch 처럼 거대한 패키지의 AST 를 재귀로 훑을 때
# 기본 재귀 한도(1000)를 넘어 RecursionError 가 난다. 한도를 올려준다.
sys.setrecursionlimit(10000)

APP = ["whisper-dictation.py"]

DATA_FILES = [
    ("templates", ["templates/dashboard.html"]),
    ("", ["dictionary.json", "hud.py", "app_paths.py", "dashboard.py", "audio_level.py"]),
]

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Qwen Dictation",
        "CFBundleDisplayName": "Qwen Dictation",
        "CFBundleIdentifier": "com.shimjaeho.qwendictation",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": "받아쓰기를 위해 마이크로 음성을 녹음합니다.",
        "NSAppleEventsUsageDescription": "받아쓴 텍스트를 현재 앱에 붙여넣기 위해 시스템 이벤트를 사용합니다.",
    },
    "packages": [
        "rumps",
        "flask",
        "pynput",
        "soundfile",
        "sounddevice",
        "numpy",
        "qwen_asr",
        "pkg_resources",
    ],
    "includes": ["torch", "torchaudio", "transformers"],
    # 아래 패키지는 앱 실행에 필요 없는데 transformers/qwen_asr 가 optional 로
    # 끌어와서 빌드를 깨뜨린다(PyInstaller 의 GTK/Qt hook, numba 의 CUDA hook 등).
    # 번들에서 제외한다.
    # 주의: scipy / librosa 는 qwen_asr/inference/utils.py 가 런타임에 실제로
    #       import 하므로(librosa.load / resample, scipy.io.wavfile) 제외 금지.
    "excludes": [
        "PyInstaller",
        "gradio",
        "gradio_client",
        "matplotlib",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "gi",
        "numba",
        "llvmlite",
        "tkinter.test",
        "test",
        "tests",
    ],
    "iconfile": None,
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
