# Qwen Dictation을 독립 .app으로 패키징 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 터미널에서 `./run.sh`로 실행하던 Qwen Dictation을 Finder에서 더블클릭으로 실행되는 `Qwen Dictation.app` 독립 앱으로 만들어, 손쉬운 사용 권한이 앱 하나에 안정적으로 붙도록 한다.

**Architecture:** `py2app`으로 `.app` 번들을 만든다. 1.8GB 모델 가중치는 번들에 넣지 않고 기존 Hugging Face 캐시(`~/.cache/huggingface`)를 그대로 참조한다(사용자 선택: "앱 밖에 두기"). 번들 안에서 깨지는 두 가지 — HUD를 `venv/bin/python` 절대경로로 호출하는 부분, 그리고 `os.path.dirname(__file__)` 기반 리소스 경로 — 를 번들 환경에서도 동작하도록 고친다. macOS 권한 팝업이 뜨도록 `Info.plist`에 마이크 사용 설명문을 넣는다.

**Tech Stack:** Python 3.11 (uv-managed venv), rumps (메뉴바), py2app (번들러), pyinstaller는 사용 안 함, qwen-asr / torch (MPS), Flask (대시보드), tkinter (HUD).

---

## 배경: 왜 이 작업인가 / 무엇이 깨지는가

현재 앱은 `./run.sh` → `venv/bin/python whisper-dictation.py` 로 실행된다. 이때 손쉬운 사용 권한은 venv가 가리키는 uv 파이썬 실행파일
(`~/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none/bin/python3.11`)에 붙는데, 이 실체는 회색으로 뜨고 경로/업데이트에 따라 권한이 풀린다. `.app`으로 만들면 권한이 `Qwen Dictation.app` 한 곳에 붙어 안정적이다.

`.app` 번들에서 반드시 깨지는 두 지점 (실측 기반):

1. **HUD 호출** — `whisper-dictation.py:201-210` `Recorder._start_hud()` 가
   `os.path.join(APP_DIR, "venv/bin/python")` 와 `os.path.join(APP_DIR, "hud.py")` 를 직접 부른다.
   번들 안에는 `venv/bin/python` 도 `hud.py` 원본 경로도 없으므로 HUD가 안 뜬다. (받아쓰기 자체엔 무관)
2. **리소스 경로** — `APP_DIR = os.path.dirname(os.path.abspath(__file__))` 및 `dashboard.py` 의
   `TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')`,
   `dictionary.json` 경로. py2app 번들에서 `__file__` 은 `.../Resources/` 아래를 가리키므로,
   `templates/dashboard.html` 와 `dictionary.json` 을 번들 리소스로 포함시키면 동작한다.
   단 `dictionary.json` 은 사용자가 대시보드로 수정하는 쓰기 대상이므로, 번들 내부(읽기전용 위치)가 아니라
   사용자 홈의 쓰기 가능한 위치(`~/.qwen-dictation/dictionary.json`)로 옮겨야 한다.

모델 경로는 손댈 필요 없다. 코드가 이미 `QWEN_ASR_0_6B_PATH` 기본값으로 HF repo id (`Qwen/Qwen3-ASR-0.6B`) 를 쓰고,
HF 라이브러리가 `~/.cache/huggingface` 캐시를 자동으로 찾는다. 번들에서도 `$HOME` 은 동일하므로 그대로 동작한다.

---

## File Structure

- **Create** `setup.py` — py2app 빌드 설정. 앱 이름, 아이콘, 포함 리소스, Info.plist(권한 설명문), 제외 패키지 지정.
- **Create** `app_paths.py` — 번들/개발 양쪽에서 동작하는 경로 헬퍼. `resource_path()`(읽기전용 리소스), `user_data_dir()`(쓰기 가능 데이터), `hud_command()`(HUD 실행 커맨드) 제공. 단일 책임: "지금 .app 안인가 개발 중인가"를 흡수.
- **Modify** `whisper-dictation.py` — `DICTIONARY_PATH`, `Recorder._start_hud()` 를 `app_paths` 사용으로 교체. dictionary 최초 1회 시드(seed) 추가.
- **Modify** `dashboard.py` — `TEMPLATES_DIR`, dictionary 읽기/쓰기 경로를 `app_paths` 사용으로 교체.
- **Modify** `.gitignore` — `build/`, `dist/` 추가.
- **No change** `hud.py`, `templates/dashboard.html`, `dictionary.json`(시드 원본으로 유지).

빌드 산출물은 `dist/Qwen Dictation.app` 에 생성된다.

---

## Task 1: 경로 헬퍼 모듈 (app_paths.py)

번들/개발 양쪽에서 동작하는 경로 결정 로직을 한 곳에 모은다. 다른 모든 수정이 이 모듈에 의존하므로 먼저 만든다.

**Files:**
- Create: `app_paths.py`
- Test: `test_app_paths.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# test_app_paths.py
import os
import app_paths


def test_resource_path_points_to_existing_template():
    p = app_paths.resource_path("templates", "dashboard.html")
    assert p.endswith(os.path.join("templates", "dashboard.html"))
    assert os.path.exists(p), f"template not found at {p}"


def test_user_data_dir_is_writable_and_created():
    d = app_paths.user_data_dir()
    assert os.path.isdir(d)
    probe = os.path.join(d, ".write_probe")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)


def test_dictionary_path_is_under_user_data_dir():
    assert app_paths.dictionary_path().startswith(app_paths.user_data_dir())


def test_hud_command_includes_hud_script():
    cmd = app_paths.hud_command(max_time=30)
    assert any("hud" in part for part in cmd)
    assert "30" in cmd
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `./venv/bin/python -m pytest test_app_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app_paths'`
(pytest 미설치 시 `./venv/bin/pip install pytest` 먼저)

- [ ] **Step 3: 최소 구현 작성**

```python
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
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `./venv/bin/python -m pytest test_app_paths.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add app_paths.py test_app_paths.py
git commit -m "feat: add app_paths helper for bundle/dev path resolution"
```

---

## Task 2: 사전 경로를 쓰기 가능한 위치로 이전 (whisper-dictation.py)

번들 내부는 읽기전용이라 대시보드의 사전 저장이 실패한다. 사전을 `~/.qwen-dictation/dictionary.json` 으로 옮기고, 최초 실행 시 동봉 시드를 복사한다.

**Files:**
- Modify: `whisper-dictation.py:24-25` (DICTIONARY_PATH 정의), `whisper-dictation.py:65-75` (apply_dictionary), `main()`
- Test: `test_dictionary_seed.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# test_dictionary_seed.py
import json
import os
import importlib.util

import app_paths


def _load_main_module():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_creates_user_dictionary(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)

    wd = _load_main_module()
    wd.ensure_dictionary()

    user_dict = app_paths.dictionary_path()
    assert os.path.exists(user_dict)
    with open(user_dict, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_apply_dictionary_uses_user_path(tmp_path, monkeypatch):
    fake_home = tmp_path / "home2"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)

    wd = _load_main_module()
    os.makedirs(app_paths.user_data_dir(), exist_ok=True)
    with open(app_paths.dictionary_path(), "w", encoding="utf-8") as f:
        json.dump({"큐엔": "Qwen"}, f, ensure_ascii=False)

    assert wd.apply_dictionary("큐엔 테스트") == "Qwen 테스트"
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `./venv/bin/python -m pytest test_dictionary_seed.py -v`
Expected: FAIL — `AttributeError: module 'wd' has no attribute 'ensure_dictionary'`

- [ ] **Step 3: 구현 작성**

`whisper-dictation.py` 상단 import에 `import app_paths` 추가 (line 21 `import dashboard` 옆).

`whisper-dictation.py:25` 의
```python
DICTIONARY_PATH = os.path.join(APP_DIR, "dictionary.json")
```
를 다음으로 교체:
```python
DICTIONARY_PATH = app_paths.dictionary_path()
```

`apply_dictionary` 바로 위(line 65 앞)에 시드 함수 추가:
```python
def ensure_dictionary():
    """사용자 사전이 없으면 동봉 시드를 복사한다(최초 1회)."""
    dest = app_paths.dictionary_path()
    if os.path.exists(dest):
        return
    seed = app_paths.seed_dictionary_path()
    try:
        if os.path.exists(seed):
            with open(seed, "r", encoding="utf-8") as src:
                data = src.read()
        else:
            data = "{}"
        with open(dest, "w", encoding="utf-8") as out:
            out.write(data)
    except Exception as exc:
        print(f"Dictionary seed error: {exc}")
```

`apply_dictionary` 내부에서 `DICTIONARY_PATH` 가 모듈 로드시점에 고정되지 않도록, 함수 안에서 매번 경로를 다시 읽게 한다. `whisper-dictation.py:66` 의
```python
    if not os.path.exists(DICTIONARY_PATH):
        return text
    try:
        with open(DICTIONARY_PATH, "r", encoding="utf-8") as file:
```
를 다음으로 교체:
```python
    path = app_paths.dictionary_path()
    if not os.path.exists(path):
        return text
    try:
        with open(path, "r", encoding="utf-8") as file:
```

`main()` 진입부(`args = parse_args()` 다음 줄)에 시드 호출 추가:
```python
    ensure_dictionary()
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `./venv/bin/python -m pytest test_dictionary_seed.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 회귀 확인 — 기존 받아쓰기 사전 치환이 여전히 동작**

Run:
```bash
./venv/bin/python -c "
import os, json, app_paths
os.makedirs(app_paths.user_data_dir(), exist_ok=True)
with open(app_paths.dictionary_path(),'w',encoding='utf-8') as f: json.dump({'큐엔':'Qwen'}, f, ensure_ascii=False)
import importlib.util
spec=importlib.util.spec_from_file_location('wd','whisper-dictation.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.apply_dictionary('큐엔 좋아요'))
"
```
Expected: `Qwen 좋아요`

- [ ] **Step 6: 커밋**

```bash
git add whisper-dictation.py test_dictionary_seed.py
git commit -m "feat: store user dictionary in ~/.qwen-dictation, seed on first run"
```

---

## Task 3: HUD 호출을 번들 호환으로 교체 (whisper-dictation.py)

`_start_hud()` 가 `venv/bin/python` 절대경로를 직접 부른다. `app_paths.hud_command()` 로 교체한다.

**Files:**
- Modify: `whisper-dictation.py:201-212` (`Recorder._start_hud`)
- Test: `test_hud_command.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# test_hud_command.py
import os
import sys
import app_paths


def test_hud_command_uses_current_interpreter():
    cmd = app_paths.hud_command(max_time=12)
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("hud.py")
    assert "--max_time" in cmd
    assert "12" in cmd


def test_hud_script_exists_at_resource_path():
    assert os.path.exists(app_paths.resource_path("hud.py"))
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

(app_paths.hud_command 는 Task 1에서 이미 구현됨 → 이 테스트는 PASS일 수 있다. 그렇다면 이 Task의 핵심은 whisper-dictation.py 호출부 교체이며, 테스트는 회귀 가드 역할이다.)

Run: `./venv/bin/python -m pytest test_hud_command.py -v`
Expected: PASS (2 passed) — 헬퍼는 이미 존재. 다음 스텝에서 호출부를 바꾼다.

- [ ] **Step 3: 호출부 교체**

`whisper-dictation.py:203-210` 의
```python
            self.hud_process = subprocess.Popen(
                [
                    os.path.join(APP_DIR, "venv/bin/python"),
                    os.path.join(APP_DIR, "hud.py"),
                    "--max_time",
                    str(int(self.app.max_time or 30)),
                ]
            )
```
를 다음으로 교체:
```python
            self.hud_process = subprocess.Popen(
                app_paths.hud_command(max_time=self.app.max_time or 30)
            )
```

- [ ] **Step 4: 컴파일 + 헬퍼 일치 확인**

Run:
```bash
./venv/bin/python -m py_compile whisper-dictation.py && ./venv/bin/python -m pytest test_hud_command.py -v
```
Expected: 컴파일 통과, 2 passed

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py test_hud_command.py
git commit -m "fix: launch HUD via sys.executable for .app bundle compatibility"
```

---

## Task 4: 대시보드 경로를 app_paths로 교체 (dashboard.py)

대시보드가 템플릿과 사전을 `os.path.dirname(__file__)` 기준으로 읽고 쓴다. 번들에서 동작하도록 `app_paths` 로 교체한다.

**Files:**
- Modify: `dashboard.py:14-15` (TEMPLATES_DIR), `dashboard.py:20` (html_path), `dashboard.py:84` (get_dictionary), `dashboard.py:96` (post_dictionary)
- Test: `test_dashboard_paths.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# test_dashboard_paths.py
import json
import os
import app_paths
import dashboard


def test_dashboard_get_dictionary_reads_user_path(tmp_path, monkeypatch):
    fake_home = tmp_path / "h"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)
    os.makedirs(app_paths.user_data_dir(), exist_ok=True)
    with open(app_paths.dictionary_path(), "w", encoding="utf-8") as f:
        json.dump({"맥북": "MacBook"}, f, ensure_ascii=False)

    client = dashboard.flask_app.test_client()
    resp = client.get("/api/dictionary")
    assert resp.status_code == 200
    assert resp.get_json().get("맥북") == "MacBook"


def test_dashboard_post_dictionary_writes_user_path(tmp_path, monkeypatch):
    fake_home = tmp_path / "h2"
    fake_home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)

    client = dashboard.flask_app.test_client()
    resp = client.post("/api/dictionary", json={"지피티": "GPT"})
    assert resp.status_code == 200
    with open(app_paths.dictionary_path(), encoding="utf-8") as f:
        assert json.load(f).get("지피티") == "GPT"
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `./venv/bin/python -m pytest test_dashboard_paths.py -v`
Expected: FAIL — 현재 dashboard.py 는 프로젝트 폴더의 dictionary.json 을 읽으므로 fake_home 위치와 불일치

- [ ] **Step 3: 구현 작성**

`dashboard.py` 상단 import에 `import app_paths` 추가 (line 5 `from flask import ...` 다음).

`dashboard.py:14-15` 의
```python
# Standard templates folder path
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')
```
를 삭제하고, `home()` 내부 `dashboard.py:20` 의
```python
        html_path = os.path.join(TEMPLATES_DIR, 'dashboard.html')
```
를 다음으로 교체:
```python
        html_path = app_paths.resource_path('templates', 'dashboard.html')
```

`get_dictionary()` `dashboard.py:84` 의
```python
    dict_path = os.path.join(os.path.dirname(__file__), 'dictionary.json')
```
를 다음으로 교체:
```python
    dict_path = app_paths.dictionary_path()
```

`post_dictionary()` `dashboard.py:96` 의
```python
    dict_path = os.path.join(os.path.dirname(__file__), 'dictionary.json')
```
를 다음으로 교체:
```python
    dict_path = app_paths.dictionary_path()
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `./venv/bin/python -m pytest test_dashboard_paths.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 전체 회귀 — 모든 테스트 + 컴파일**

Run:
```bash
./venv/bin/python -m py_compile whisper-dictation.py dashboard.py hud.py app_paths.py
./venv/bin/python -m pytest -v
```
Expected: 컴파일 통과, 모든 테스트 PASS

- [ ] **Step 6: 커밋**

```bash
git add dashboard.py test_dashboard_paths.py
git commit -m "fix: resolve dashboard template/dictionary paths via app_paths"
```

---

## Task 5: py2app 빌드 설정 (setup.py)

`.app` 번들을 만드는 py2app 설정. 모델은 제외(외부 캐시 참조), 권한 설명문은 Info.plist에 포함.

**Files:**
- Create: `setup.py`
- Modify: `.gitignore` (build/, dist/ 추가)

- [ ] **Step 1: py2app 설치**

Run: `./venv/bin/pip install py2app`
Expected: `Successfully installed py2app-...`

- [ ] **Step 2: setup.py 작성**

```python
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
    ("", ["dictionary.json", "hud.py", "app_paths.py", "dashboard.py"]),
]

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Qwen Dictation",
        "CFBundleDisplayName": "Qwen Dictation",
        "CFBundleIdentifier": "com.shimjaeho.qwendictation",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSUIElement": True,  # 메뉴바 전용 앱(Dock 아이콘 숨김)
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
    # 무거운/불필요 패키지는 제외해 번들 크기와 빌드 시간을 줄인다.
    # torch 는 packages 에 넣지 않고 includes 로 최소 포함 시도하되,
    # 빌드 실패 시 Task 6 에서 packages 로 승격한다.
    "includes": ["torch", "torchaudio", "transformers"],
    "excludes": ["tkinter"],  # HUD는 별도 프로세스이므로 메인 번들에서 제외 가능. 문제시 Task6에서 해제.
    "iconfile": None,
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
```

> 주의(실행자용): py2app은 torch 같은 거대 네이티브 패키지에서 첫 빌드가 잘 깨진다. 이 setup.py는 1차 시도용이며, 깨지면 Task 6의 진단 절차로 옵션을 조정한다. 이건 예상된 반복이다.

- [ ] **Step 3: .gitignore 갱신**

`.gitignore` 끝에 추가:
```
build/
dist/
```

- [ ] **Step 4: 커밋(빌드 전에 설정만)**

```bash
git add setup.py .gitignore
git commit -m "build: add py2app setup.py for .app packaging"
```

---

## Task 6: 빌드 및 실행 검증 (반복 단계)

실제로 `.app` 을 만들고, 더블클릭 실행이 아니라 우선 **콘솔에서 직접 실행**해 로그를 보며 깨진 곳을 잡는다.

**Files:** 없음(빌드/디버그). 필요한 수정은 setup.py 또는 app_paths.py 로 되돌아가 반영.

- [ ] **Step 1: 클린 빌드**

Run:
```bash
rm -rf build dist
./venv/bin/python setup.py py2app 2>&1 | tail -30
```
Expected: `dist/Qwen Dictation.app` 생성. (경고는 많아도 됨, 에러로 중단되지 않으면 통과)

- [ ] **Step 2: 번들 내부 실행파일로 직접 실행(로그 확인)**

Run:
```bash
"dist/Qwen Dictation.app/Contents/MacOS/Qwen Dictation" 2>&1 | tee /tmp/qwen_app_run.log &
sleep 25
grep -iE "error|traceback|modulenotfound|no module|not trusted|Dashboard" /tmp/qwen_app_run.log | head -20
```
Expected 성공 신호: 로그에 `Settings Dashboard background server started` 가 보이고,
`ModuleNotFoundError`/`Traceback` 가 없음. (`not trusted` 는 권한 미부여 신호이며 빌드 실패가 아님 — Task 7에서 처리)

- [ ] **Step 3: 분기 — import 에러가 있으면 setup.py 조정**

만약 `ModuleNotFoundError: No module named 'X'` 가 보이면:
- `X` 를 `OPTIONS["packages"]` 리스트에 추가.
- torch 관련 `Library not loaded` / dylib 에러면 `includes` 의 `torch`/`torchaudio` 를 `packages` 로 이동.
- 그 후 Step 1(클린 빌드)부터 다시.

이 분기를 **에러가 사라질 때까지 반복**한다. (경험상 1~3회)

- [ ] **Step 4: 분기 — 대시보드 200 확인**

앱이 떠 있는 상태에서:
Run: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5001/`
Expected: `200`
실패(연결 거부)면 Step 2 로그에서 Flask/템플릿 경로 에러를 찾아 app_paths/ setup.py DATA_FILES 를 점검.

- [ ] **Step 5: 떠 있는 테스트 앱 종료**

Run: `pkill -f "Qwen Dictation.app/Contents/MacOS" || true`

- [ ] **Step 6: 빌드 성공 기록 커밋(설정 변경이 있었다면)**

```bash
git add setup.py app_paths.py
git commit -m "build: fix py2app bundling (resolve import/resource issues)"
```
(이번 Task에서 수정이 없었다면 커밋 생략)

---

## Task 7: 권한 부여 + 실사용 검증 (사용자 동반 필수)

여기는 **사용자가 직접** macOS 권한을 켜고 마이크로 말해야 하는 단계. 자동화 불가. 실행자는 안내문을 정확히 제공하고, 사용자 피드백을 받아 잔여 버그만 처리한다.

**Files:** 없음(잔여 수정 시 해당 파일로 복귀)

- [ ] **Step 1: 앱을 응용 프로그램에 설치(선택) 또는 dist에서 실행**

사용자 안내:
> Finder에서 `dist/Qwen Dictation.app` 을 더블클릭하세요. (원하면 응용 프로그램 폴더로 드래그)

- [ ] **Step 2: 권한 부여 안내**

사용자 안내(순서대로):
> 1. 시스템 설정 → 개인정보 보호 및 보안 → **손쉬운 사용** → 목록에서 **Qwen Dictation** 켜기 (없으면 `+`로 `dist`의 .app 추가)
> 2. 같은 화면의 **마이크** 에서도 Qwen Dictation 켜기 (말할 때 팝업이 뜨면 허용)
> 3. 붙여넣기 시 **자동화** 팝업("System Events 제어")이 뜨면 허용
> 4. 권한 켠 뒤 앱을 **완전히 종료 후 재실행** (메뉴바 아이콘 → Quit, 다시 더블클릭)

- [ ] **Step 3: 실사용 1회 테스트(사용자 수행)**

사용자 안내:
> 메모장이나 크롬 입력창에 커서를 두고, 설정된 단축키(기본 `cmd_l+alt`, 또는 메뉴바에서 모드 확인)를 눌러 말한 뒤 다시 눌러 멈추세요. 받아쓴 글이 입력되는지 확인.

성공 기준: 글자가 포커스된 입력창에 들어온다. "not trusted" 콘솔 메시지가 더 이상 안 뜬다.

- [ ] **Step 4: 잔여 버그 분류**

사용자 피드백에 따라:
- 단축키 무반응 → 손쉬운 사용 권한/재실행 재확인.
- 붙여넣기 무동작 → 자동화 권한 또는 `paste_text` AppleScript 분기(앱별 메뉴명) 점검.
- HUD 안 뜸 → `app_paths.hud_command` 가 번들에서 tkinter를 못 찾는 경우. setup.py `excludes`에서 tkinter 제거 후 재빌드, 또는 HUD를 일시적으로 비활성.
- 모델 로딩 실패 → `~/.cache/huggingface` 캐시 존재 확인, 없으면 `huggingface-cli download` 안내.

- [ ] **Step 5: README에 .app 빌드/설치 절차 문서화**

`README.md` 에 "## App Build (.app)" 섹션 추가:
```markdown
## App Build (.app)

Build a standalone menu-bar app (model weights are NOT bundled; they are read
from the existing `~/.cache/huggingface` cache):

\`\`\`bash
./venv/bin/python setup.py py2app
open "dist/Qwen Dictation.app"
\`\`\`

First launch needs Accessibility + Microphone permission granted to
**Qwen Dictation** in System Settings → Privacy & Security. Quit and relaunch
after granting. User dictionary lives at `~/.qwen-dictation/dictionary.json`.
```

- [ ] **Step 6: 최종 커밋**

```bash
git add README.md
git commit -m "docs: document .app build and first-launch permission setup"
```

---

## Self-Review (작성자 점검 결과)

**1. 스펙 커버리지:** 목표(터미널 → .app, 권한 안정화, 모델 외부 참조)
- .app 생성 → Task 5,6 ✓
- 모델 외부 참조 → 코드 무변경으로 충족, 배경/Task5 주석에 명시 ✓
- 권한 안정화 → .app 단위 권한 + Task 7 안내 ✓
- 번들에서 깨지는 HUD/리소스/사전쓰기 → Task 1,2,3,4 ✓

**2. 플레이스홀더 스캔:** "적절히 처리" 류 없음. 모든 코드 스텝에 실제 코드 포함. Task 6/7의 분기는 "조건 → 구체 조치"로 명시(빌드 디버깅 특성상 분기 자체가 내용). ✓

**3. 타입/이름 일치:** `app_paths` 의 `resource_path`, `user_data_dir`, `dictionary_path`, `seed_dictionary_path`, `hud_command` 가 Task 1 정의 → Task 2,3,4에서 동일 이름으로 사용됨. `ensure_dictionary` Task 2 정의 → main()에서 호출. dashboard `flask_app` 기존 이름 사용. ✓

**알려진 리스크(실행자 인지용):** torch의 py2app 번들링은 가장 깨지기 쉬운 부분. Task 6이 반복 단계로 설계된 이유. 최악의 경우 py2app 대신 PyInstaller로 전환해야 할 수 있으나, 그 전에 Task 6 분기(packages 승격)를 모두 시도한다.
