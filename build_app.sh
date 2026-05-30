#!/bin/bash
# PyInstaller 빌드 스크립트 (py2app 는 Python 3.11 과 비호환이라 대체).
# 산출물: dist/Qwen Dictation.app
#
# 모델 가중치(1.8GB)는 번들에 넣지 않는다. 실행 시 ~/.cache/huggingface 의
# 기존 Qwen3-ASR 캐시를 그대로 참조한다.
#
# nagisa 처리(중요): qwen_asr 의 forced aligner 가 nagisa 를 import 한다.
# nagisa 의 train.py 는 `import model / import prepro / from tagger import Tagger`
# 같은 bare import 를 쓰는데, nagisa/tagger.py 가 로드 시 자기 패키지 디렉터리를
# sys.path 에 append 하기 때문에 그 .py 파일들이 디스크상의 nagisa 디렉터리에
# "파일로" 존재하면 bare import 가 해소된다. PyInstaller 는 nagisa_utils 의 .so
# 때문에 디스크에 nagisa/ 디렉터리를 만들지만 순수 파이썬 .py 는 PYZ 안에만 넣어
# 디스크에는 없다. 그래서 아래에서 nagisa 소스 .py 들을 디스크 디렉터리로 함께
# 복사(--add-data)해 패키지를 완성한다. site-packages 는 건드리지 않는다.
#
# 메뉴바 전용 앱(LSUIElement)과 마이크/AppleEvents 권한 문자열은 빌드 후
# fix_plist.py 로 Info.plist 에 주입한다(PyInstaller 가 직접 못 넣음).
set -e
cd "$(dirname "$0")"

# 하이픈이 든 메인 파일은 import 불가하므로 import 가능한 이름으로 복사한다.
cp whisper-dictation.py app_main.py

NAGISA_DIR="$(./venv/bin/python -c 'import os, nagisa; print(os.path.dirname(nagisa.__file__))')"

rm -rf build dist
./venv/bin/pyinstaller --noconfirm --windowed --name "Qwen Dictation" \
  --osx-bundle-identifier com.shimjaeho.qwendictation \
  --add-data "templates/dashboard.html:templates" \
  --add-data "dictionary.json:." \
  --add-data "hud.py:." \
  --add-data "dashboard.py:." \
  --add-data "audio_level.py:." \
  --add-data "app_paths.py:." \
  --add-data "${NAGISA_DIR}/__init__.py:nagisa" \
  --add-data "${NAGISA_DIR}/train.py:nagisa" \
  --add-data "${NAGISA_DIR}/tagger.py:nagisa" \
  --add-data "${NAGISA_DIR}/model.py:nagisa" \
  --add-data "${NAGISA_DIR}/prepro.py:nagisa" \
  --add-data "${NAGISA_DIR}/mecab_system_eval.py:nagisa" \
  --collect-all qwen_asr \
  --collect-all transformers \
  --collect-all nagisa \
  --collect-all librosa \
  --collect-submodules torch \
  --collect-submodules torchaudio \
  --collect-submodules sklearn \
  --collect-submodules scipy \
  --hidden-import rumps \
  --hidden-import hud_overlay \
  --collect-submodules objc \
  --hidden-import AppKit \
  --hidden-import Foundation \
  --hidden-import Quartz \
  --hidden-import flask \
  --hidden-import pynput \
  --hidden-import pynput.keyboard \
  --hidden-import pynput.mouse \
  --hidden-import soundfile \
  --hidden-import pyaudio \
  --hidden-import lazy_loader \
  --hidden-import soxr \
  --hidden-import audioread \
  --copy-metadata torch --copy-metadata tqdm --copy-metadata regex \
  --copy-metadata numpy --copy-metadata tokenizers --copy-metadata safetensors \
  app_main.py

./venv/bin/python fix_plist.py "dist/Qwen Dictation.app/Contents/Info.plist"

echo "BUILD OK -> dist/Qwen Dictation.app"
