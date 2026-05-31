# 설정 저장 · 녹음시간 제한 해제 · 수의안과 사전 · 기본 1.7b Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Qwen Dictation 앱에 네 가지 실사용 개선을 더한다 — ①설정이 앱 재시작 후에도 유지되고, ②녹음 30초 자동중단 제한을 없애고, ③자주 틀리는 수의안과 용어를 사전에 미리 넣어 자동 교정하고, ④기본 모델을 정확한 1.7b로 바꾼다.

**Architecture:** 새 모듈 `app_config.py` 가 사용자 설정을 `~/.qwen-dictation/config.json` 에 읽고 쓴다(사전이 사는 곳과 같은 쓰기 가능 디렉터리). `StatusBarApp` 은 시작 시 저장된 설정을 불러와 적용하고, 설정이 바뀔 때마다 저장한다. 녹음 자동중단은 `max_time` 이 0이면 끄도록 바꾼다(0 = 무제한). 수의안과 용어는 사전 시드(`dictionary.json`)에 추가하고, 기존 사용자에게도 빠진 항목만 병합한다. 기본 모델 상수만 1.7b로 바꾼다.

**Tech Stack:** Python 3.11 (uv venv), rumps(메뉴바), Flask(대시보드, 포트 5001), 기존 모듈 `app_paths.py`(쓰기 경로 헬퍼). 테스트는 pytest. `whisper-dictation.py` 는 하이픈 파일이라 테스트에서 importlib로 로드.

---

## 배경: 현재 동작과 무엇을 바꾸나 (실측 기반)

- **설정 비영속**: `StatusBarApp.__init__`(whisper-dictation.py:371-402)이 `mode`/`selected_model`/`stream_interval`/`max_time`/`current_language` 를 메모리에만 둔다. `dashboard.py` 의 `post_config` 는 이 필드들을 바꾸지만 디스크에 저장하지 않는다 → 앱 재시작하면 초기화. 사전(`dictionary.json`)만 디스크에 저장됨.
- **30초 제한**: `parse_args`(whisper-dictation.py:517)의 `--max_time` 기본값 30, 그리고 `start_app`(whisper-dictation.py:462-464)에서 `if self.max_time is not None:` 일 때 `threading.Timer(self.max_time, ...)` 로 자동중단 타이머를 건다. 즉 30초 뒤 강제 정지.
- **사전**: `~/.qwen-dictation/dictionary.json` (최초 실행 시 번들 시드 `dictionary.json` 에서 복사). 현재 IT 용어만 있음. `apply_dictionary`(whisper-dictation.py:85-96)가 단순 `str.replace(source, replacement)` 로 치환.
- **기본 모델**: `StatusBarApp.__init__`(whisper-dictation.py:377)의 `self.selected_model = "0.6b"` 와 `parse_args`(whisper-dictation.py:519)의 `--model-size` 기본 `"0.6b"`, 그리고 main()(whisper-dictation.py:533)의 `app.selected_model = args.model_size`.

**테스트 경계(중요):** `StatusBarApp` 은 `rumps.App` 상속이라 헤드리스 테스트에서 인스턴스화가 불안정하다. 그래서 **순수 로직은 별도 모듈로 빼서 테스트**하고(`app_config.py`, 사전 병합 함수), `StatusBarApp`/`dashboard` 배선은 `py_compile` + 사용자 실제 실행으로 검증한다. 이 경계는 기존 테스트들이 whisper-dictation 런타임 클래스를 직접 안 건드린 것과 같은 방침이다.

---

## File Structure

- **Create** `app_config.py` — 설정 영속 모듈. `config_path()`, `DEFAULTS`, `load_config()`, `save_config(dict)`. 단일 책임: 설정 디스크 입출력.
- **Create** `vet_terms.py` — 수의안과 교정쌍 상수 `VET_TERMS`(dict) + `merge_terms_into(dict)→dict` 순수 함수. 단일 책임: 도메인 용어 데이터 + 병합 로직(테스트 가능).
- **Modify** `whisper-dictation.py` — ①시작 시 설정 로드·적용, ②설정 변경 시 저장, ③`max_time` 0=무제한 처리, ④기본 모델 1.7b, ⑤사전에 수의안과 용어 병합 호출.
- **Modify** `dashboard.py` — `post_config` 가 설정 변경 후 `app_instance.save_settings()` 호출.
- **Modify** `dictionary.json`(시드) — 관찰된 수의안과 오인식 교정쌍 추가.
- **Test** `test_app_config.py`, `test_vet_terms.py`.

---

## Task 1: 설정 영속 모듈 (app_config.py)

설정을 `~/.qwen-dictation/config.json` 에 읽고 쓰는 순수 모듈. 다른 변경들이 여기 의존하므로 먼저.

**Files:**
- Create: `app_config.py`
- Test: `test_app_config.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# test_app_config.py
import json
import os
import app_config


def test_defaults_have_required_keys():
    for k in ["mode", "language", "model_size", "stream_interval", "max_time"]:
        assert k in app_config.DEFAULTS


def test_load_returns_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "config_path", lambda: str(tmp_path / "config.json"))
    cfg = app_config.load_config()
    assert cfg["model_size"] == app_config.DEFAULTS["model_size"]
    assert cfg["mode"] == app_config.DEFAULTS["mode"]


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "config_path", lambda: str(tmp_path / "config.json"))
    app_config.save_config({"mode": "batch_paste", "model_size": "1.7b",
                            "language": "ko", "stream_interval": 1.5, "max_time": 0})
    cfg = app_config.load_config()
    assert cfg["mode"] == "batch_paste"
    assert cfg["model_size"] == "1.7b"
    assert cfg["max_time"] == 0


def test_load_ignores_unknown_keys_and_fills_missing(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "config_path", lambda: str(p))
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"mode": "streaming", "bogus": 123}, f)
    cfg = app_config.load_config()
    assert cfg["mode"] == "streaming"
    assert "bogus" not in cfg
    assert cfg["model_size"] == app_config.DEFAULTS["model_size"]  # 빠진 키는 기본값


def test_load_handles_corrupt_file(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "config_path", lambda: str(p))
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ not valid json")
    cfg = app_config.load_config()  # 깨져도 예외 없이 기본값
    assert cfg["model_size"] == app_config.DEFAULTS["model_size"]
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/python -m pytest test_app_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app_config'`

- [ ] **Step 3: 구현**

```python
# app_config.py
"""사용자 설정을 ~/.qwen-dictation/config.json 에 읽고 쓰는 모듈.

설정은 사전(dictionary.json)과 같은 쓰기 가능 디렉터리에 저장되어
앱(.app) 재시작 후에도 유지된다.
"""
import json
import os

import app_paths

# max_time=0 은 "자동중단 없음(무제한)" 을 뜻한다.
DEFAULTS = {
    "mode": "streaming",
    "language": "ko",
    "model_size": "1.7b",
    "stream_interval": 1.2,
    "max_time": 0,
}


def config_path():
    return os.path.join(app_paths.user_data_dir(), "config.json")


def load_config():
    """저장된 설정을 읽어 DEFAULTS 위에 덮어 반환. 없거나 깨지면 DEFAULTS."""
    cfg = dict(DEFAULTS)
    try:
        p = config_path()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k in DEFAULTS:
                    if k in saved:
                        cfg[k] = saved[k]
    except Exception as exc:
        print(f"Config load error: {exc}")
    return cfg


def save_config(cfg):
    """DEFAULTS 의 키만 추려서 저장(미지의 키 무시)."""
    try:
        data = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"Config save error: {exc}")
```

- [ ] **Step 4: 통과 확인**

Run: `./venv/bin/python -m pytest test_app_config.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add app_config.py test_app_config.py
git commit -m "feat: add app_config for persisting user settings to ~/.qwen-dictation/config.json

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 수의안과 용어 + 병합 로직 (vet_terms.py)

관찰된 오인식 교정쌍을 데이터로 두고, 기존 사용자 사전에 빠진 것만 병합하는 순수 함수.

**Files:**
- Create: `vet_terms.py`
- Test: `test_vet_terms.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# test_vet_terms.py
import vet_terms


def test_vet_terms_is_nonempty_dict():
    assert isinstance(vet_terms.VET_TERMS, dict)
    assert len(vet_terms.VET_TERMS) >= 3


def test_merge_adds_missing_terms():
    existing = {"큐엔": "Qwen"}
    merged = vet_terms.merge_terms_into(existing)
    assert merged["큐엔"] == "Qwen"           # 기존 보존
    assert "괴양" in merged                    # 신규 추가
    assert merged["괴양"] == "궤양"


def test_merge_does_not_overwrite_user_value():
    existing = {"괴양": "내가직접정한값"}
    merged = vet_terms.merge_terms_into(existing)
    assert merged["괴양"] == "내가직접정한값"   # 사용자 값 우선


def test_merge_returns_new_dict_not_mutate():
    existing = {"큐엔": "Qwen"}
    merged = vet_terms.merge_terms_into(existing)
    assert "괴양" not in existing               # 원본 불변
    assert merged is not existing
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/python -m pytest test_vet_terms.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vet_terms'`

- [ ] **Step 3: 구현**

관찰된(실측) 오인식만 보수적으로 넣는다. 추가 용어는 사용자가 대시보드에서 직접 채운다(도메인 결정).

```python
# vet_terms.py
"""수의안과 받아쓰기에서 자주 나는 오인식 교정쌍.

값은 '잘못 들린 표기' -> '올바른 표기'. 본 테스트 중 실제로 관찰된 것만
보수적으로 담는다. 사용자는 대시보드에서 자기 용어를 추가한다.
"""

VET_TERMS = {
    "괴양": "궤양",      # 형광 염색 테스트 중 관찰
    "강막": "각막",      # '강막궤양' 오인식 관찰
    "영색": "염색",      # '형광 영색' 오인식 관찰
}


def merge_terms_into(existing):
    """기존 사전(dict)에 VET_TERMS 중 빠진 키만 더해 새 dict 반환.

    사용자가 이미 정의한 키는 절대 덮어쓰지 않는다. 원본은 변경하지 않는다.
    """
    merged = dict(existing)
    for k, v in VET_TERMS.items():
        if k not in merged:
            merged[k] = v
    return merged
```

- [ ] **Step 4: 통과 확인**

Run: `./venv/bin/python -m pytest test_vet_terms.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add vet_terms.py test_vet_terms.py
git commit -m "feat: add vet ophthalmology term corrections with non-destructive merge

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 시드 사전에 수의안과 용어 추가 (dictionary.json)

새 설치 사용자가 처음부터 교정을 받도록 번들 시드에도 반영.

**Files:**
- Modify: `dictionary.json`

- [ ] **Step 1: 현재 시드 확인**

Run: `cat dictionary.json`
Expected: IT 용어들(큐엔→Qwen 등) JSON.

- [ ] **Step 2: 수의안과 교정쌍 추가**

`dictionary.json` 에 아래 세 키를 추가(기존 키는 그대로 유지). 파일이 유효한 JSON이어야 하므로 마지막 항목 콤마 주의. 최종 형태 예(기존 IT 키 + 신규 3개):

```json
{
  "깃허브": "GitHub",
  "맥북": "MacBook",
  "스포큰리": "Spokenly",
  "아이폰": "iPhone",
  "에스티티": "STT",
  "에이아이": "AI",
  "오픈소스": "Open Source",
  "지피티": "GPT",
  "체트지피티": "ChatGPT",
  "큐엔": "Qwen",
  "클러드": "Claude",
  "타입리스": "Typeless",
  "파이썬": "Python",
  "괴양": "궤양",
  "강막": "각막",
  "영색": "염색"
}
```

(주의: 위 IT 키 목록은 현재 파일에 있는 것을 그대로 두라는 뜻이다. Step 1에서 실제 내용을 확인하고, **기존 키를 보존한 채** 뒤의 3개만 추가하라. 기존 키 철자가 위와 다르면 실제 파일 기준을 따른다.)

- [ ] **Step 3: JSON 유효성 + 치환 동작 확인**

Run:
```bash
./venv/bin/python -c "
import json
d = json.load(open('dictionary.json', encoding='utf-8'))
assert d.get('괴양') == '궤양' and d.get('강막') == '각막' and d.get('영색') == '염색'
print('SEED_OK keys=', len(d))
"
```
Expected: `SEED_OK keys= 16`

- [ ] **Step 4: 커밋**

```bash
git add dictionary.json
git commit -m "feat: seed dictionary with vet ophthalmology corrections

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 앱에 설정 로드/저장 + 무제한 녹음 + 기본 1.7b 배선 (whisper-dictation.py)

`StatusBarApp` 이 시작 시 저장된 설정을 적용하고, 변경 시 저장하며, `max_time=0` 이면 자동중단을 끄고, 기본 모델을 1.7b로, 시작 시 수의안과 용어를 사전에 병합한다.

**Files:**
- Modify: `whisper-dictation.py` — imports, `StatusBarApp.__init__`(371-408), `set_mode`(432-438), `change_language`(449-451), `start_app`(453-466), `parse_args`(496-520), `main`(523-542); 신규 메서드 `save_settings`/`current_config`/`_apply_saved_config`; 신규 함수 `merge_vet_terms`.
- Test: 없음(헤드리스 rumps 불안정 → py_compile + 통합 점검으로 검증).

- [ ] **Step 1: import 추가**

`whisper-dictation.py` 상단 로컬 import 영역(`import app_paths` 옆, line 22 부근)에 추가:
```python
import app_config
import vet_terms
```

- [ ] **Step 2: 사전 병합 함수 추가**

`ensure_dictionary` 함수 바로 아래(whisper-dictation.py:83 부근)에 추가:
```python
def merge_vet_terms():
    """사용자 사전에 수의안과 교정쌍 중 빠진 것을 더한다(기존 값 보존)."""
    path = app_paths.dictionary_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        if not isinstance(data, dict):
            return
        merged = vet_terms.merge_terms_into(data)
        if merged != data:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"Vet term merge error: {exc}")
```

- [ ] **Step 3: 기본 모델 상수 1.7b로**

`StatusBarApp.__init__`(whisper-dictation.py:377)의
```python
        self.selected_model = "0.6b"
```
를:
```python
        self.selected_model = "1.7b"
```

`parse_args`(whisper-dictation.py:519)의
```python
    parser.add_argument("--model-size", choices=("0.6b", "1.7b"), default="0.6b")
```
를:
```python
    parser.add_argument("--model-size", choices=("0.6b", "1.7b"), default="1.7b")
```

`parse_args`(whisper-dictation.py:517)의 max_time 기본값을 0(무제한)으로:
```python
    parser.add_argument("-t", "--max_time", type=float, default=30)
```
를:
```python
    parser.add_argument("-t", "--max_time", type=float, default=0)
```

- [ ] **Step 4: 설정 로드/저장 메서드 추가 + __init__ 에서 적용**

`StatusBarApp.__init__` 끝부분, `self.sync_menu_state()`(whisper-dictation.py:402) 다음 줄에 저장된 설정 적용 호출을 넣는다. 즉 402행 직후에:
```python
        self._apply_saved_config()
```
그리고 `sync_menu_state` 메서드(422행) 위에 세 메서드를 추가:
```python
    def current_config(self):
        return {
            "mode": self.mode,
            "language": self.current_language,
            "model_size": self.selected_model,
            "stream_interval": self.stream_interval,
            "max_time": self.max_time or 0,
        }

    def save_settings(self):
        app_config.save_config(self.current_config())

    def _apply_saved_config(self):
        cfg = app_config.load_config()
        self.mode = cfg["mode"]
        self.current_language = cfg["language"]
        self.selected_model = cfg["model_size"]
        self.stream_interval = cfg["stream_interval"]
        self.max_time = cfg["max_time"]
        self.sync_menu_state()
```

- [ ] **Step 5: 설정 변경 시 저장**

`set_mode`(whisper-dictation.py:432-438)의 끝(`self.sync_menu_state()` 다음)에:
```python
        self.save_settings()
```

`change_language`(whisper-dictation.py:449-451)의 끝(`self.sync_menu_state()` 다음)에:
```python
        self.save_settings()
```

- [ ] **Step 6: 무제한 녹음 처리**

`start_app`(whisper-dictation.py:462-464)의
```python
        if self.max_time is not None:
            self.timer = threading.Timer(self.max_time, lambda: self.stop_app(None))
            self.timer.start()
```
를:
```python
        if self.max_time and self.max_time > 0:
            self.timer = threading.Timer(self.max_time, lambda: self.stop_app(None))
            self.timer.start()
```
(max_time 이 0 또는 None 이면 자동중단 타이머를 걸지 않음 = 무제한. 사용자가 직접 단축키로 멈춤.)

- [ ] **Step 7: main() 정리 — 저장 설정이 CLI 기본값에 안 밀리도록**

`main`(whisper-dictation.py:523-525)에서 `ensure_dictionary()` 다음에 수의안과 병합 호출 추가:
```python
    ensure_dictionary()
    merge_vet_terms()
```

`main`(whisper-dictation.py:532-533)의
```python
    app.k_double_cmd = args.k_double_cmd
    app.selected_model = args.model_size
```
중 **`app.selected_model = args.model_size` 줄을 삭제**한다(저장된 설정/기본 1.7b 가 `__init__` 에서 이미 적용되므로, 여기서 덮으면 영속 설정이 무시됨). `app.k_double_cmd = args.k_double_cmd` 는 유지.

(참고: 이로써 `--model-size` CLI 플래그는 비활성화된다. 이 앱은 보통 .app으로 인자 없이 실행되고 모델은 대시보드/저장설정으로 정하므로 의도된 동작이다.)

- [ ] **Step 8: 컴파일 확인**

Run: `./venv/bin/python -m py_compile whisper-dictation.py app_config.py vet_terms.py`
Expected: 출력 없음(성공).

- [ ] **Step 9: 통합 점검 — 설정 저장/로드 + 병합이 실제로 도는지 (rumps 없이)**

`StatusBarApp` 은 못 띄우지만, 핵심 로직 모듈은 실제 경로로 돌려 확인:
```bash
./venv/bin/python -c "
import os, json, tempfile, app_config, vet_terms, app_paths
# 임시 홈으로 격리
home = tempfile.mkdtemp()
os.path.expanduser = (lambda f: (lambda p: home if p=='~' else f(p)))(os.path.expanduser)
# 1) 저장→로드
app_config.save_config({'mode':'batch_paste','model_size':'1.7b','language':'ko','stream_interval':1.2,'max_time':0})
c = app_config.load_config()
assert c['mode']=='batch_paste' and c['model_size']=='1.7b' and c['max_time']==0, c
# 2) 사전 병합
os.makedirs(app_paths.user_data_dir(), exist_ok=True)
open(app_paths.dictionary_path(),'w',encoding='utf-8').write(json.dumps({'큐엔':'Qwen'}, ensure_ascii=False))
d = json.load(open(app_paths.dictionary_path(), encoding='utf-8'))
m = vet_terms.merge_terms_into(d)
assert m['큐엔']=='Qwen' and m['괴양']=='궤양', m
print('INTEGRATION_OK', c['model_size'], len(m))
"
```
Expected: `INTEGRATION_OK 1.7b 4`

- [ ] **Step 10: 전체 테스트 회귀**

Run: `./venv/bin/python -m pytest -q`
Expected: 이전 15 + 신규 9 = **24 passed** (test_app_config 5 + test_vet_terms 4).

- [ ] **Step 11: 커밋**

```bash
git add whisper-dictation.py
git commit -m "feat: persist settings, unlimited recording (max_time=0), default 1.7b, seed vet terms

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 대시보드가 설정 변경 시 저장하게 (dashboard.py)

대시보드에서 모드/언어/모델/간격/시간을 바꾸면 즉시 디스크에 저장.

**Files:**
- Modify: `dashboard.py` — `post_config`

- [ ] **Step 1: post_config 끝에 저장 호출 추가**

`dashboard.py` 의 `post_config` 함수에서, 모든 필드 반영이 끝나고 `return jsonify(...)` 직전에 추가:
```python
    if hasattr(app_instance, "save_settings"):
        app_instance.save_settings()
```
(현재 `post_config` 는 `app_instance` 의 mode/language/model_size/stream_interval/max_time 을 갱신한 뒤 `return jsonify({"status": "success", "config": get_config().json})` 한다. 그 return 바로 앞에 위 두 줄을 넣는다. `hasattr` 가드는 테스트의 가짜 app_instance 호환용.)

- [ ] **Step 2: 컴파일 + 전체 테스트**

Run:
```bash
./venv/bin/python -m py_compile dashboard.py
./venv/bin/python -m pytest -q
```
Expected: 컴파일 성공, `24 passed`.

- [ ] **Step 3: 대시보드 저장 통합 점검**

가짜 app_instance 로 POST 후 config.json 이 써지는지:
```bash
./venv/bin/python -c "
import os, json, tempfile, types
import app_config, app_paths, dashboard
home = tempfile.mkdtemp()
os.path.expanduser = (lambda f: (lambda p: home if p=='~' else f(p)))(os.path.expanduser)
class Fake:
    mode='streaming'; current_language='ko'; languages=['ko','en']
    k_double_cmd=False; selected_model='1.7b'; stream_interval=1.2; max_time=0; started=False; elapsed_time=0
    def set_mode(self, m): self.mode=m
    def sync_menu_state(self): pass
    def save_settings(self): app_config.save_config({'mode':self.mode,'language':self.current_language,'model_size':self.selected_model,'stream_interval':self.stream_interval,'max_time':self.max_time or 0})
dashboard.app_instance = Fake()
c = dashboard.flask_app.test_client()
r = c.post('/api/dictionary', json={'테스트':'OK'})  # 사전 경로 살아있나 확인
r2 = c.post('/api/config', json={'mode':'batch_paste','model_size':'1.7b'})
assert r2.status_code == 200, r2.status_code
saved = json.load(open(app_config.config_path(), encoding='utf-8'))
assert saved['mode']=='batch_paste', saved
print('DASH_SAVE_OK', saved['mode'], saved['model_size'])
"
```
Expected: `DASH_SAVE_OK batch_paste 1.7b`

- [ ] **Step 4: 커밋**

```bash
git add dashboard.py
git commit -m "feat: persist settings when changed via dashboard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 앱 아이콘 생성 (make_icon.py → AppIcon.icns)

마이크·음파 느낌의 깔끔한 아이콘을 코드로 그려 `.icns` 로 만들고, 메뉴바 아이콘도 전용 이미지로 교체한다.

**Files:**
- Create: `make_icon.py` (아이콘 생성 스크립트), `assets/AppIcon.icns`(생성물), `assets/menubar.png`(메뉴바용 흑백 템플릿)
- Modify: `build_app.sh`(아이콘을 번들에 포함), `whisper-dictation.py`(메뉴바 아이콘 이미지 사용)

- [ ] **Step 1: 아이콘 생성 스크립트 작성**

`make_icon.py` 를 만든다. PIL 로 둥근 사각 바탕 + 마이크 + 음파를 그리고, `iconutil` 로 `.icns` 를 만든다. 또 메뉴바용 작은 흑백(template) PNG도 출력한다.

```python
# make_icon.py
"""앱 아이콘(.icns)과 메뉴바 템플릿 PNG를 코드로 생성한다.

실행: ./venv/bin/python make_icon.py
산출물: assets/AppIcon.icns, assets/menubar.png
필요 도구: PIL(설치됨), iconutil/sips(macOS 기본)
"""
import math
import os
import shutil
import subprocess

from PIL import Image, ImageDraw

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(ASSETS, exist_ok=True)


def _rounded(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_app_icon(size):
    """앱 아이콘 한 장(size x size)을 그려서 RGBA 이미지 반환."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 짙은 남색 둥근 사각 바탕(그라데이션 흉내: 두 겹)
    margin = int(size * 0.06)
    _rounded(d, (margin, margin, size - margin, size - margin),
             radius=int(size * 0.22), fill=(11, 15, 25, 255))      # #0b0f19
    _rounded(d, (margin, margin, size - margin, int(size * 0.62)),
             radius=int(size * 0.22), fill=(49, 46, 129, 90))      # 위쪽 보라 하이라이트

    # 마이크 본체(둥근 캡슐)
    cx = size * 0.5
    mic_w = size * 0.20
    mic_top = size * 0.24
    mic_bot = size * 0.56
    _rounded(d, (cx - mic_w / 2, mic_top, cx + mic_w / 2, mic_bot),
             radius=int(mic_w / 2), fill=(243, 244, 246, 255))     # #f3f4f6

    # 마이크 받침(아치 + 스탠드)
    arc_box = (cx - mic_w * 0.95, mic_top + mic_w * 0.2,
               cx + mic_w * 0.95, mic_bot + mic_w * 0.6)
    d.arc(arc_box, start=20, end=160, fill=(165, 180, 252, 255),
          width=max(2, int(size * 0.022)))                          # #a5b4fc
    stand_top = mic_bot + mic_w * 0.6
    d.line((cx, stand_top, cx, stand_top + size * 0.08),
           fill=(165, 180, 252, 255), width=max(2, int(size * 0.022)))
    d.line((cx - size * 0.07, stand_top + size * 0.08,
            cx + size * 0.07, stand_top + size * 0.08),
           fill=(165, 180, 252, 255), width=max(2, int(size * 0.022)))

    # 음파(좌우 초록 곡선 두 줄) — 받아쓰기 '소리' 상징
    for i, r in enumerate((0.16, 0.24)):
        col = (34, 197, 94, 255) if i == 0 else (34, 197, 94, 160)  # #22c55e
        for sign in (-1, 1):
            bx = cx + sign * (mic_w * 0.5 + size * r)
            box = (bx - size * r, size * 0.30, bx + size * r, size * 0.50)
            start, end = (300, 60) if sign > 0 else (120, 240)
            d.arc(box, start=start, end=end, fill=col,
                  width=max(2, int(size * 0.020)))
    return img


def draw_menubar(size=44):
    """메뉴바용 흑백 template 이미지(투명 배경에 검은 마이크 실루엣)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = size * 0.5
    mic_w = size * 0.34
    _rounded(d, (cx - mic_w / 2, size * 0.18, cx + mic_w / 2, size * 0.60),
             radius=int(mic_w / 2), fill=(0, 0, 0, 255))
    d.arc((cx - mic_w * 0.95, size * 0.30, cx + mic_w * 0.95, size * 0.72),
          start=20, end=160, fill=(0, 0, 0, 255), width=max(2, int(size * 0.06)))
    d.line((cx, size * 0.72, cx, size * 0.84), fill=(0, 0, 0, 255),
           width=max(2, int(size * 0.06)))
    return img


def build_icns():
    iconset = os.path.join(ASSETS, "AppIcon.iconset")
    if os.path.exists(iconset):
        shutil.rmtree(iconset)
    os.makedirs(iconset)
    specs = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
             (256, 1), (256, 2), (512, 1), (512, 2)]
    for base, scale in specs:
        px = base * scale
        img = draw_app_icon(px)
        name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
        img.save(os.path.join(iconset, name))
    icns = os.path.join(ASSETS, "AppIcon.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)
    shutil.rmtree(iconset)
    return icns


def main():
    icns = build_icns()
    mb = draw_menubar(44)
    mb.save(os.path.join(ASSETS, "menubar.png"))
    print("ICON_OK", icns, os.path.join(ASSETS, "menubar.png"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 아이콘 생성 실행**

Run: `./venv/bin/python make_icon.py`
Expected: `ICON_OK .../assets/AppIcon.icns .../assets/menubar.png`, 그리고 두 파일이 생긴다.
검증: `ls -la assets/AppIcon.icns assets/menubar.png` → 둘 다 0바이트 아님.

- [ ] **Step 3: 메뉴바 아이콘을 이미지로 교체**

`whisper-dictation.py` 의 `StatusBarApp.__init__`(whisper-dictation.py:373) 의
```python
        super().__init__("Qwen Dictation", "⏯")
```
를 다음으로 교체(아이콘 파일이 있으면 쓰고, 없으면 기존 기호로 폴백):
```python
        _mb = app_paths.resource_path("assets", "menubar.png")
        if os.path.exists(_mb):
            super().__init__("Qwen Dictation", icon=_mb, template=True)
        else:
            super().__init__("Qwen Dictation", "⏯")
```
(rumps 는 `template=True` 면 메뉴바 다크/라이트에 맞춰 자동 반전. `app_paths`/`os` 는 이미 import 됨.)

녹음 중 제목을 시간으로 바꾸는 `update_title`(whisper-dictation.py:482-487)과 정지 시 `self.title = "⏯"`(stop_app, whisper-dictation.py:475)은 그대로 두되, 정지 시 기호 대신 빈 제목이 자연스러우므로 `self.title = "⏯"` 를 `self.title = None` 로 바꾼다(아이콘만 표시). 만약 None 이 rumps 에서 문제되면 `""` 로 둔다.

- [ ] **Step 4: build_app.sh 에 아이콘 포함**

`build_app.sh` 를 읽고, PyInstaller 명령에 아이콘 옵션과 데이터 추가:
- 앱 아이콘: `--icon assets/AppIcon.icns`
- 메뉴바 PNG 동봉: `--add-data "assets/menubar.png:assets"`
(이미 `--add-data` 들이 있는 위치에 맞춰 같은 형식으로 추가. `--icon` 은 한 번만.)

`fix_plist.py` 가 plist 를 후처리한다면 `CFBundleIconFile`/`CFBundleIconName` 이 `AppIcon` 으로 들어가는지 확인하고, 없으면 추가한다.

- [ ] **Step 5: 컴파일 + 테스트 회귀**

Run:
```bash
./venv/bin/python -m py_compile whisper-dictation.py make_icon.py
./venv/bin/python -m pytest -q
```
Expected: 컴파일 성공, `24 passed`(아이콘은 테스트 영향 없음).

- [ ] **Step 6: 커밋**

```bash
git add make_icon.py assets/AppIcon.icns assets/menubar.png build_app.sh whisper-dictation.py fix_plist.py
git commit -m "feat: app icon (mic + soundwave) and menubar template image

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(참고: `assets/AppIcon.icns`/`menubar.png` 는 생성물이지만 빌드 재현성을 위해 커밋한다. .gitignore 가 assets 를 막지 않는지 확인.)

---

## Task 7: .app 재빌드 + 문서 갱신

새 모듈·아이콘이 번들에 들어가게 다시 빌드하고, 동작/저장위치를 문서화.

**Files:**
- Modify: `build_app.sh`(필요 시 hidden-import 추가), `README.md`, `CLAUDE.md`

- [ ] **Step 1: build_app.sh 에 새 모듈 포함 확인**

`build_app.sh` 를 읽는다. `app_config.py`/`vet_terms.py` 는 `whisper-dictation.py`(→ app_main.py)가 일반 import 하므로 PyInstaller가 자동 포함한다. 안전하게 hidden-import 가 명시적이면 추가, 아니면 변경 없음:
```bash
# (필요 시) pyinstaller 명령에 추가
--hidden-import app_config --hidden-import vet_terms
```
판단: 자동수집되면 변경하지 말 것(YAGNI). 빌드 후 Step 3에서 import 에러가 나면 그때 추가.

- [ ] **Step 2: 재빌드**

Run: `bash build_app.sh 2>&1 | tail -20`
Expected: `dist/Qwen Dictation.app` 재생성, 치명적 에러 없음.

- [ ] **Step 3: 번들 실행 점검**

Run:
```bash
pkill -f "Qwen Dictation.app/Contents/MacOS" 2>/dev/null; sleep 1
( "dist/Qwen Dictation.app/Contents/MacOS/Qwen Dictation" > /tmp/qwen_imp_run.log 2>&1 & P=$!; sleep 35; kill $P 2>/dev/null )
grep -iE "error|traceback|no module|app_config|vet_terms|Dashboard|Initializing" /tmp/qwen_imp_run.log | head -20
pkill -f "Qwen Dictation.app/Contents/MacOS" || true
```
Expected: `app_config`/`vet_terms` import 에러 없음, "Settings Dashboard background server started" 보임. (없으면 Step 1의 hidden-import 추가 후 재빌드.)

- [ ] **Step 4: 문서 갱신**

`README.md` 의 "Personal Dictionary" 인근에 한 단락 추가:
```markdown
## Settings persistence

Settings (mode, language, model size, stream interval, max recording time) are
saved to `~/.qwen-dictation/config.json` and restored on next launch. The user
dictionary lives at `~/.qwen-dictation/dictionary.json`. Recording has no time
limit by default (`max_time = 0`); set a positive value to auto-stop.
The default model is **1.7b** (more accurate; ~0.2s slower than 0.6b once loaded).
```

`CLAUDE.md` 의 "Config persistence gotcha" 문구가 있으면 갱신(이제 설정이 저장되므로): 기존 "설정은 저장 안 됨" 서술을 "설정은 `~/.qwen-dictation/config.json` 에 저장됨, 사전은 dictionary.json" 으로 정정.

- [ ] **Step 5: 커밋**

```bash
git add build_app.sh README.md CLAUDE.md
git commit -m "build: rebuild .app with config/vet modules; document settings persistence

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (작성자 점검)

**1. 스펙 커버리지 (사용자가 고른 4개):**
- 설정 저장 → Task 1(모듈) + Task 4(앱 배선) + Task 5(대시보드) ✓
- 녹음 30초 제한 해제 → Task 4 Step 3·6 (max_time 기본 0, 0이면 타이머 안 걸음) ✓
- 수의안과 용어 사전 → Task 2(데이터+병합) + Task 3(시드) + Task 4 Step 2·7(병합 호출) ✓
- 기본 모델 1.7b → Task 4 Step 3 (두 곳 기본값 + main 덮어쓰기 제거) + app_config DEFAULTS ✓
- 앱 아이콘 → Task 6(make_icon.py → AppIcon.icns + 메뉴바 template, 빌드/배선 포함) ✓
- 자동 실행(login item) → **사용자가 명시적으로 제외**, 계획에 없음 ✓

**2. 플레이스홀더 스캔:** "적절히 처리" 류 없음. 모든 코드 스텝에 실제 코드. Task 6 Step 1의 hidden-import는 "에러 나면 추가"라는 조건부지만 구체 명령 제시 ✓

**3. 타입/이름 일치:** `app_config.DEFAULTS/load_config/save_config/config_path`, `vet_terms.VET_TERMS/merge_terms_into`, `StatusBarApp.current_config/save_settings/_apply_saved_config`, `merge_vet_terms` — Task 1·2에서 정의된 이름이 Task 4·5에서 동일하게 사용됨 ✓. `model_size` 키 일관(대시보드·config 모두) ✓. max_time 0=무제한 의미가 DEFAULTS·parse_args·start_app 에서 일관 ✓.

**알려진 한계(실행자 인지):** ①`StatusBarApp` 자체는 헤드리스 테스트 불가라 통합 점검(Step 9/Step 3) + 사용자 실제 실행으로 검증한다. ②`--model-size` CLI 플래그는 의도적으로 비활성(영속 설정 우선). ③수의안과 교정쌍은 관찰된 3개만 보수적으로 시드하고, 나머지는 사용자가 대시보드에서 추가(도메인 결정).
