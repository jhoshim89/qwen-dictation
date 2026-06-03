# app_paths.py
"""번들(.app)과 개발(소스 실행) 양쪽에서 동작하는 경로 헬퍼.

py2app/PyInstaller 번들에서는 리소스가 sys._MEIPASS 아래에 놓이고,
개발 중에는 이 파일이 있는 디렉터리가 곧 프로젝트 루트다.
"""
import os
import sys

APP_NAME = "Qwen Dictation"

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def is_frozen():
    return getattr(sys, "frozen", False)


def resource_path(*parts):
    """읽기전용 리소스(templates 등)의 절대경로.

    PyInstaller 번들에서는 sys._MEIPASS 아래에서 찾고,
    개발 중에는 이 모듈이 있는 디렉터리 기준으로 찾는다.
    """
    base = getattr(sys, "_MEIPASS", None) or _THIS_DIR
    return os.path.join(base, *parts)


def user_data_dir():
    """사용자가 쓰기 가능한 데이터 디렉터리. 없으면 만든다."""
    d = os.path.join(os.path.expanduser("~"), ".qwen-dictation")
    os.makedirs(d, exist_ok=True)
    return d


def vocabulary_path():
    """사용자 단어 목록 파일 경로(쓰기 가능 위치)."""
    return os.path.join(user_data_dir(), "vocabulary.json")


def history_path():
    """최근 받아쓰기 텍스트 기록 파일 경로."""
    return os.path.join(user_data_dir(), "history.json")


def vocabulary_candidates_path():
    """승인 전 단어 후보와 숨김 상태 파일 경로."""
    return os.path.join(user_data_dir(), "vocabulary-candidates.json")
