# app_paths.py
"""번들(.app)과 개발(소스 실행) 양쪽에서 동작하는 경로 헬퍼.

py2app 번들에서는 sys.frozen 이 설정되고 __file__ 이 .../Resources/ 아래를 가리킨다.
개발 중에는 이 파일이 있는 디렉터리가 곧 프로젝트 루트다.
"""
import os
import sys

APP_NAME = "Qwen Dictation"

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def is_frozen():
    return getattr(sys, "frozen", False)


def resource_path(*parts):
    """읽기전용 리소스(templates 등)의 절대경로."""
    return os.path.join(_THIS_DIR, *parts)


def user_data_dir():
    """사용자가 쓰기 가능한 데이터 디렉터리. 없으면 만든다."""
    d = os.path.join(os.path.expanduser("~"), ".qwen-dictation")
    os.makedirs(d, exist_ok=True)
    return d


def dictionary_path():
    """사용자 사전 파일 경로(쓰기 가능 위치)."""
    return os.path.join(user_data_dir(), "dictionary.json")


def seed_dictionary_path():
    """앱에 기본 동봉되는 사전 시드(읽기전용)."""
    return resource_path("dictionary.json")


def hud_command(max_time=30):
    """HUD 오버레이를 띄우는 subprocess 커맨드 리스트.

    번들에서는 번들 내부 파이썬(sys.executable)으로 hud.py 를 실행하고,
    개발 중에는 동일하게 현재 인터프리터로 실행한다.
    """
    return [sys.executable, resource_path("hud.py"), "--max_time", str(int(max_time))]
