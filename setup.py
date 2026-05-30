# setup.py
"""py2app 빌드 설정.

빌드:   ./venv/bin/python setup.py py2app
산출물: dist/Qwen Dictation.app

모델 가중치(1.8GB)는 번들에 넣지 않는다. 앱은 실행 시 ~/.cache/huggingface 의
기존 Qwen3-ASR 캐시를 그대로 참조한다.
"""
from setuptools import setup

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
        "qwen_asr",
        "soundfile",
        "numpy",
    ],
    "includes": ["torch", "torchaudio", "transformers"],
    "excludes": ["tkinter"],
    "iconfile": None,
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
