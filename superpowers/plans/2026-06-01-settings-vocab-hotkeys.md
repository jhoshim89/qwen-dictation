# 설정 정리(0.6b 제거) + 사전→단어등록 교체 + 단축키 사용자 설정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ①모델 선택에서 0.6b를 없애고 1.7b만 남긴다. ②"듣고 난 뒤 바꿔치기" 사전을 "자주 쓰는 말을 미리 등록해 잘 알아듣게" 하는 단어 등록(Qwen `context` 바이어싱)으로 교체한다. ③단축키 방식과 키를 대시보드에서 고르고 저장·즉시적용한다.

**Architecture:** 세 부분은 독립적이라 순서대로 커밋 가능하다. (A) 0.6b는 UI/CLI/기본값에서 제거하고 stale 설정은 1.7b로 보정. (B) 새 `vocabulary.py`가 단어 목록을 읽고/쓰고/이전(migration)하며, `transcribe_file`이 그 목록을 `model.transcribe(context=...)`로 넘긴다; `apply_dictionary`는 제거. (C) 단축키 생성을 `StatusBarApp.apply_hotkey_config()`로 옮겨, 돌고 있는 전역 pynput 리스너를 멈췄다 새 키로 다시 시작한다; 대시보드가 설정 변경 시 이 메서드를 호출.

**Tech Stack:** Python 3.11, pynput(전역 단축키), Flask(대시보드 5001), qwen_asr(`transcribe(..., context=...)`), pytest. `whisper-dictation.py`는 하이픈이라 importlib 로드.

**Verify 공통:** `./venv/bin/python -m py_compile whisper-dictation.py dashboard.py hud_overlay.py vocabulary.py app_config.py app_paths.py` 와 `./venv/bin/python -m pytest -q`.

**현재 테스트 수:** 42 passed (시작점).

---

## File Structure

- **Modify** `whisper-dictation.py`: `transcribe_file`(context 사용+0.6b 기본 제거), `get_model`(0.6b 분기 제거), `parse_args`(--model-size/--hotkeys 기본), `main`(ensure_vocabulary + apply_hotkey_config 로 단순화), `StatusBarApp`(hotkey 상태/`build_key_listener`/`apply_hotkey_config`), 상단에 `key_from_name`/`validate_hotkey_config`/`HOTKEY_KEY_NAMES`, `MultiHotkeyListener.__init__`(키 인자), `apply_dictionary`/`ensure_dictionary`/`merge_vet_terms` 제거.
- **Create** `vocabulary.py`: 단어 목록 load/save/migrate/build_context.
- **Modify** `app_paths.py`: `vocabulary_path()`.
- **Modify** `app_config.py`: DEFAULTS 에 hotkey 3개 + model_size 보정.
- **Modify** `dashboard.py`: `/api/config`에 hotkey 필드, `/api/dictionary`→`/api/vocabulary`(리스트), model_size 기본 1.7b.
- **Modify** `templates/dashboard.html`: 모델 0.6b 항목 제거, 사전 UI→단어목록 UI, 단축키 설정 UI.
- **Test** `test_model_size.py`, `test_vocabulary.py`, `test_transcribe_context.py`, `test_hotkey_config.py`.
- **Keep** `vet_terms.py`(이제 단어목록 시드 출처로만 사용; `merge_terms_into`/`test_vet_terms.py`는 그대로 두되 호출은 안 함).

---

# PART A — 0.6b 제거

## Task A1: 저장된 stale model_size 를 1.7b 로 보정

**Files:**
- Modify: `app_config.py`
- Test: `test_model_size.py`

- [ ] **Step 1: 실패 테스트**

```python
# test_model_size.py
import json
import app_config


def test_stale_0_6b_is_coerced_to_1_7b(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"model_size": "0.6b"}), encoding="utf-8")
    monkeypatch.setattr(app_config, "config_path", lambda: str(cfg_file))
    cfg = app_config.load_config()
    assert cfg["model_size"] == "1.7b"


def test_valid_model_size_preserved(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"model_size": "1.7b"}), encoding="utf-8")
    monkeypatch.setattr(app_config, "config_path", lambda: str(cfg_file))
    assert app_config.load_config()["model_size"] == "1.7b"
```

- [ ] **Step 2: 실패 확인** — `./venv/bin/python -m pytest test_model_size.py -v` → 첫 테스트 FAIL(0.6b 그대로 반환).

- [ ] **Step 3: 구현** — `app_config.py` `load_config()` 의 `return cfg` 바로 앞에 보정 추가:

```python
    if cfg.get("model_size") != "1.7b":
        cfg["model_size"] = "1.7b"
    return cfg
```

- [ ] **Step 4: 통과 확인** — `./venv/bin/python -m pytest test_model_size.py -v` → 2 passed.

- [ ] **Step 5: 커밋**

```bash
git add app_config.py test_model_size.py
git commit -m "fix: coerce stale 0.6b model_size to 1.7b on load"
```

## Task A2: 0.6b 를 코드·UI·CLI 에서 제거

**Files:**
- Modify: `whisper-dictation.py` (`get_model`, `transcribe_file`, `parse_args`)
- Modify: `dashboard.py` (config 기본값)
- Modify: `templates/dashboard.html` (옵션·JS 기본)
- Test: `test_model_size.py` (추가)

- [ ] **Step 1: 실패 테스트 추가** (`test_model_size.py` 끝에):

```python
import importlib.util


def _load_wd():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_default_model_is_1_7b(monkeypatch):
    wd = _load_wd()
    monkeypatch.setattr("sys.argv", ["whisper-dictation.py"])
    args = wd.parse_args()
    assert args.model_size == "1.7b"


def test_cli_rejects_0_6b(monkeypatch):
    wd = _load_wd()
    monkeypatch.setattr("sys.argv", ["whisper-dictation.py", "--model-size", "0.6b"])
    import pytest
    with pytest.raises(SystemExit):
        wd.parse_args()
```

- [ ] **Step 2: 실패 확인** — `test_cli_rejects_0_6b` FAIL(0.6b 아직 허용).

- [ ] **Step 3: 구현**

(a) `whisper-dictation.py` `transcribe_file` 시그니처 기본값 변경:
```python
    def transcribe_file(self, audio_path, language=None, model_size="1.7b"):
```

(b) `get_model` 의 0.6b 분기 제거 — 현재 `if model_size == "1.7b": ... return self.model_1_7b` 다음에 오는 `if self.model_0_6b is None: ... return self.model_0_6b` 블록(라인 ~219-227)을 다음으로 교체:
```python
            # 0.6b 는 제거됨 — 항상 1.7b 사용.
            return self.model_1_7b
```
(주의: 들여쓰기는 `with self.model_lock:` 내부. `self.model_0_6b`/`MODEL_0_6B` 참조가 남으면 안 됨 — `__init__` 의 `self.model_0_6b = None` 은 그대로 둬도 무방하나, 사용처가 사라졌으니 함께 지워도 된다.)

(c) `parse_args` 의 model-size 인자:
```python
    parser.add_argument("--model-size", choices=("1.7b",), default="1.7b")
```

(d) `dashboard.py` 라인 36:
```python
        "model_size": getattr(app_instance, 'selected_model', '1.7b'),
```

(e) `templates/dashboard.html` 모델 select(라인 ~230-232)에서 0.6b 옵션 줄 삭제 — `<option value="0.6b">Qwen3-ASR 0.6B</option>` 제거. JS 기본값(라인 ~288):
```javascript
                    document.getElementById("model-size").value = data.model_size || "1.7b";
```

- [ ] **Step 4: 통과 + 회귀** — `./venv/bin/python -m py_compile whisper-dictation.py dashboard.py` 후 `./venv/bin/python -m pytest -q` → 이전 42 + A1(2) + A2(2) = **46 passed**.

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py dashboard.py templates/dashboard.html test_model_size.py
git commit -m "feat: remove 0.6b model option everywhere; default to 1.7b"
```

---

# PART B — 사전 → 단어 등록(context 바이어싱)

설계: `vocabulary.json` 은 문자열 리스트(`["Qwen", "각막", "궤양", ...]`). 받아쓸 때 `", ".join(vocab)` 을 `model.transcribe(context=...)` 로 넘긴다. 최초 1회 이전: `vocabulary.json` 이 없으면 기존 `dictionary.json` 의 **값(올바른 표기)** + `vet_terms.VET_TERMS` 의 **값** 을 합쳐 시드. 기존 `apply_dictionary` 바꿔치기는 제거.

## Task B1: vocabulary 모듈 + 경로

**Files:**
- Modify: `app_paths.py`
- Create: `vocabulary.py`
- Test: `test_vocabulary.py`

- [ ] **Step 1: 실패 테스트**

```python
# test_vocabulary.py
import json
import app_paths
import vocabulary


def _point_to_tmp(tmp_path, monkeypatch):
    vp = tmp_path / "vocabulary.json"
    dp = tmp_path / "dictionary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    monkeypatch.setattr(app_paths, "dictionary_path", lambda: str(dp))
    return vp, dp


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    vocabulary.save_vocabulary(["Qwen", "각막"])
    assert vocabulary.load_vocabulary() == ["Qwen", "각막"]


def test_load_missing_returns_empty(tmp_path, monkeypatch):
    _point_to_tmp(tmp_path, monkeypatch)
    assert vocabulary.load_vocabulary() == []


def test_build_context_joins_with_comma(tmp_path, monkeypatch):
    assert vocabulary.build_context(["각막", "궤양"]) == "각막, 궤양"
    assert vocabulary.build_context([]) == ""


def test_ensure_seeds_from_dictionary_values_and_vet_terms(tmp_path, monkeypatch):
    vp, dp = _point_to_tmp(tmp_path, monkeypatch)
    dp.write_text(json.dumps({"큐엔": "Qwen", "각막": "각막"}), encoding="utf-8")
    vocabulary.ensure_vocabulary()
    words = vocabulary.load_vocabulary()
    assert "Qwen" in words          # dictionary 의 값
    assert "각막" in words
    assert "궤양" in words          # vet_terms 의 값(괴양->궤양)
    # 중복 없음
    assert len(words) == len(set(words))


def test_ensure_does_not_overwrite_existing(tmp_path, monkeypatch):
    vp, dp = _point_to_tmp(tmp_path, monkeypatch)
    vp.write_text(json.dumps(["내단어"]), encoding="utf-8")
    vocabulary.ensure_vocabulary()
    assert vocabulary.load_vocabulary() == ["내단어"]
```

- [ ] **Step 2: 실패 확인** — `./venv/bin/python -m pytest test_vocabulary.py -v` → ImportError/AttributeError.

- [ ] **Step 3: 구현**

(a) `app_paths.py` 에 추가(`dictionary_path` 아래):
```python
def vocabulary_path():
    """사용자 단어 목록 파일 경로(쓰기 가능 위치)."""
    return os.path.join(user_data_dir(), "vocabulary.json")
```

(b) `vocabulary.py` 새로 작성:
```python
# vocabulary.py
"""받아쓰기 단어 등록(context 바이어싱) 목록을 읽고/쓰고/이전한다.

목록은 문자열 리스트. 받아쓸 때 이 단어들을 Qwen 에 미리 알려(context)
전문용어·이름을 더 잘 인식하게 한다. (확정 치환이 아니라 인식 편향)
"""
import json
import os

import app_paths
import vet_terms


def load_vocabulary():
    path = app_paths.vocabulary_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(w) for w in data if str(w).strip()]
    except Exception as exc:
        print(f"Vocabulary load error: {exc}")
    return []


def save_vocabulary(words):
    seen = set()
    cleaned = []
    for w in words:
        w = str(w).strip()
        if w and w not in seen:
            seen.add(w)
            cleaned.append(w)
    try:
        with open(app_paths.vocabulary_path(), "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"Vocabulary save error: {exc}")
    return cleaned


def build_context(words):
    """단어 목록 → model.transcribe 의 context 문자열."""
    return ", ".join(w for w in words if w)


def ensure_vocabulary():
    """vocabulary.json 이 없으면 기존 사전 값 + 수의용어 값으로 시드(최초 1회)."""
    path = app_paths.vocabulary_path()
    if os.path.exists(path):
        return
    seed = []
    seen = set()

    def add(w):
        w = str(w).strip()
        if w and w not in seen:
            seen.add(w)
            seed.append(w)

    dpath = app_paths.dictionary_path()
    if os.path.exists(dpath):
        try:
            with open(dpath, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                for v in d.values():
                    add(v)
        except Exception as exc:
            print(f"Vocabulary seed(dict) error: {exc}")
    for v in vet_terms.VET_TERMS.values():
        add(v)
    save_vocabulary(seed)
```

- [ ] **Step 4: 통과 확인** — `./venv/bin/python -m pytest test_vocabulary.py -v` → 5 passed.

- [ ] **Step 5: 커밋**

```bash
git add app_paths.py vocabulary.py test_vocabulary.py
git commit -m "feat: vocabulary module (load/save/build_context/migrate from dictionary+vet_terms)"
```

## Task B2: transcribe_file 가 context 사용 + apply_dictionary 제거 + main 시딩 교체

**Files:**
- Modify: `whisper-dictation.py`
- Test: `test_transcribe_context.py`

- [ ] **Step 1: 실패 테스트**

```python
# test_transcribe_context.py
import importlib.util
import app_paths
import vocabulary


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResult:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, context="", language=None, **kw):
        self.calls.append({"audio": audio, "context": context, "language": language})
        return [_FakeResult("녹음 결과")]


def test_transcribe_passes_vocabulary_context(tmp_path, monkeypatch):
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["각막", "궤양"])

    tr = wd.SpeechTranscriber("cpu", None)
    fake = _FakeModel()
    monkeypatch.setattr(tr, "get_model", lambda size: fake)

    out = tr.transcribe_file("/tmp/x.wav", language="Korean", model_size="1.7b")
    assert out == "녹음 결과"
    assert fake.calls[0]["context"] == "각막, 궤양"


def test_no_apply_dictionary_symbol(tmp_path, monkeypatch):
    wd = _load()
    # 바꿔치기 사전 함수는 제거되었어야 한다.
    assert not hasattr(wd, "apply_dictionary")
```

- [ ] **Step 2: 실패 확인** — context 미전달 / `apply_dictionary` 아직 존재로 FAIL.

- [ ] **Step 3: 구현**

(a) `transcribe_file` 교체:
```python
    def transcribe_file(self, audio_path, language=None, model_size="1.7b"):
        model = self.get_model(model_size)
        language = normalize_language(language)
        context = vocabulary.build_context(vocabulary.load_vocabulary())
        results = model.transcribe(audio_path, context=context, language=language)
        if not results:
            return ""
        return results[0].text.strip()
```

(b) 상단 import 에 `import vocabulary` 추가(`import vet_terms` 근처).

(c) `apply_dictionary`, `ensure_dictionary`, `merge_vet_terms` 함수 정의 3개 삭제.

(d) `main()` 의
```python
    ensure_dictionary()
    merge_vet_terms()
```
를
```python
    vocabulary.ensure_vocabulary()
```
로 교체.

- [ ] **Step 4: 통과 + 회귀** — `./venv/bin/python -m py_compile whisper-dictation.py` 후 `./venv/bin/python -m pytest -q`. 주의: `test_dictionary_seed.py` 가 `ensure_dictionary`/`merge_vet_terms` 를 검사하면 깨진다 → 그 파일은 삭제(기능 제거됨): `git rm test_dictionary_seed.py`. (`test_vet_terms.py` 는 `vet_terms.merge_terms_into` 순수함수만 보므로 유지.)
  Expected: 46 - (제거된 dictionary_seed 테스트 수) + B1(5) + B2(2) passed, 실패 0.

- [ ] **Step 5: 커밋**

```bash
git rm test_dictionary_seed.py 2>/dev/null || true
git add whisper-dictation.py test_transcribe_context.py
git commit -m "feat: transcribe with vocabulary context; remove find-replace dictionary"
```

## Task B3: 대시보드 API 를 /api/vocabulary 로 교체

**Files:**
- Modify: `dashboard.py`
- Test: `test_vocabulary.py` (API 추가)

- [ ] **Step 1: 실패 테스트 추가** (`test_vocabulary.py` 끝):

```python
def test_api_vocabulary_get_post(tmp_path, monkeypatch):
    import dashboard
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(tmp_path / "vocabulary.json"))
    client = dashboard.flask_app.test_client()
    # POST 리스트
    r = client.post("/api/vocabulary", json=["Qwen", "각막", "각막"])
    assert r.status_code == 200
    # 중복 제거되어 저장
    assert vocabulary.load_vocabulary() == ["Qwen", "각막"]
    # GET 반환
    g = client.get("/api/vocabulary")
    assert g.get_json() == ["Qwen", "각막"]
```

- [ ] **Step 2: 실패 확인** — 404(라우트 없음).

- [ ] **Step 3: 구현** — `dashboard.py` 의 `/api/dictionary` GET/POST 두 라우트(라인 83-107)를 다음으로 교체하고 상단에 `import vocabulary` 추가:

```python
@flask_app.route('/api/vocabulary', methods=['GET'])
def get_vocabulary():
    return jsonify(vocabulary.load_vocabulary())


@flask_app.route('/api/vocabulary', methods=['POST'])
def post_vocabulary():
    data = request.json
    if not isinstance(data, list):
        return jsonify({"error": "expected a list of words"}), 400
    cleaned = vocabulary.save_vocabulary(data)
    return jsonify(cleaned)
```

- [ ] **Step 4: 통과 + 회귀** — `./venv/bin/python -m pytest -q` 통과.

- [ ] **Step 5: 커밋**

```bash
git add dashboard.py test_vocabulary.py
git commit -m "feat: /api/vocabulary GET/POST (word list) replacing /api/dictionary"
```

## Task B4: 대시보드 UI 를 단어 목록 편집으로 교체

**Files:**
- Modify: `templates/dashboard.html`
- Test: 없음(UI — import/구문은 페이지 로드로, 동작은 사용자 실행)

- [ ] **Step 1: 사전 UI → 단어목록 UI**

`templates/dashboard.html` 의 기존 "사전" 영역(제목 + 입력칸 + 목록 렌더)을 단어목록 편집으로 바꾼다. 키-값 입력 두 칸을 **단어 한 줄에 하나** 텍스트영역으로 단순화:
```html
                <h2>단어 등록</h2>
                <p class="hint">자주 쓰는 말(전문용어·이름)을 한 줄에 하나씩. 미리 알려주면 더 잘 알아듣습니다.</p>
                <textarea id="vocab-list" rows="10" style="width:100%"></textarea>
                <button onclick="saveVocabulary()">단어 저장</button>
```

- [ ] **Step 2: JS 교체**

기존 dictionary 관련 JS(`let dictionary`, `fetch("/api/dictionary")`, 렌더/추가/삭제 함수)를 제거하고 다음으로 교체:
```javascript
        function loadVocabulary() {
            fetch("/api/vocabulary")
                .then(r => r.json())
                .then(words => {
                    document.getElementById("vocab-list").value = (words || []).join("\n");
                });
        }

        function saveVocabulary() {
            const words = document.getElementById("vocab-list").value
                .split("\n").map(s => s.trim()).filter(Boolean);
            fetch("/api/vocabulary", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(words),
            })
            .then(r => r.json())
            .then(saved => { document.getElementById("vocab-list").value = (saved || []).join("\n"); });
        }
```
그리고 `DOMContentLoaded` 핸들러에서 기존 `loadDictionary()` 호출을 `loadVocabulary()` 로 바꾼다.

- [ ] **Step 3: 페이지 로드 점검** — 앱 실행 후 `curl -s http://127.0.0.1:5001/ | grep -c vocab-list` ≥1, `curl -s http://127.0.0.1:5001/api/vocabulary` 가 JSON 리스트 반환. (또는 사용자가 브라우저로 확인.)

- [ ] **Step 4: 커밋**

```bash
git add templates/dashboard.html
git commit -m "feat: dashboard word-list editor replacing dictionary editor"
```

---

# PART C — 단축키 사용자 설정

설계: 단축키 키이름은 안전한 오른쪽 보조키 4종(`alt_r`/`cmd_r`/`ctrl_r`/`shift_r`)으로 제한. `MultiHotkeyListener` 는 hold/toggle 키를 인자로 받는다. `StatusBarApp.apply_hotkey_config()` 가 현재 설정으로 key_listener 를 만들고, 돌던 전역 pynput 리스너를 멈춘 뒤 새로 시작(리뷰 래퍼+intercept 포함). 대시보드 변경 시 이 메서드 호출 → 즉시 적용.

## Task C1: 키이름 매핑 + 검증 순수 함수

**Files:**
- Modify: `whisper-dictation.py` (모듈 최상위, `decide_review_action` 근처)
- Test: `test_hotkey_config.py`

- [ ] **Step 1: 실패 테스트**

```python
# test_hotkey_config.py
import importlib.util
from pynput import keyboard


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_key_from_name_known():
    wd = _load()
    assert wd.key_from_name("alt_r") == keyboard.Key.alt_r
    assert wd.key_from_name("cmd_r") == keyboard.Key.cmd_r
    assert wd.key_from_name("ctrl_r") == keyboard.Key.ctrl_r
    assert wd.key_from_name("shift_r") == keyboard.Key.shift_r


def test_key_from_name_unknown_falls_back():
    wd = _load()
    assert wd.key_from_name("nope") == keyboard.Key.alt_r


def test_validate_rejects_same_keys_in_multi():
    wd = _load()
    ok, _ = wd.validate_hotkey_config("multi", "cmd_r", "cmd_r")
    assert ok is False


def test_validate_accepts_distinct_multi():
    wd = _load()
    ok, err = wd.validate_hotkey_config("multi", "alt_r", "cmd_r")
    assert ok is True and err == ""


def test_validate_rejects_unknown_mode():
    wd = _load()
    ok, _ = wd.validate_hotkey_config("weird", "alt_r", "cmd_r")
    assert ok is False
```

- [ ] **Step 2: 실패 확인** — AttributeError.

- [ ] **Step 3: 구현** — `decide_review_action` 정의 바로 아래에 추가:

```python
HOTKEY_KEY_NAMES = {
    "alt_r": keyboard.Key.alt_r,
    "cmd_r": keyboard.Key.cmd_r,
    "ctrl_r": keyboard.Key.ctrl_r,
    "shift_r": keyboard.Key.shift_r,
}
HOTKEY_MODES = ("multi", "single", "double")


def key_from_name(name):
    """단축키 키이름 → pynput Key. 모르는 이름은 오른쪽 Option 으로."""
    return HOTKEY_KEY_NAMES.get(name, keyboard.Key.alt_r)


def validate_hotkey_config(mode, hold_key, toggle_key):
    """(ok, error). multi 에서 hold==toggle 이면 거부, 모르는 mode 거부."""
    if mode not in HOTKEY_MODES:
        return False, f"unknown hotkey mode: {mode}"
    if mode == "multi" and hold_key == toggle_key:
        return False, "hold and toggle keys must differ"
    return True, ""
```

- [ ] **Step 4: 통과 확인** — `./venv/bin/python -m pytest test_hotkey_config.py -v` → 5 passed.

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py test_hotkey_config.py
git commit -m "feat: key_from_name + validate_hotkey_config (right-side modifiers, distinct in multi)"
```

## Task C2: MultiHotkeyListener 가 키를 인자로 받음

**Files:**
- Modify: `whisper-dictation.py`
- Test: `test_hotkey_config.py` (추가)

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_multi_listener_accepts_custom_keys():
    wd = _load()
    lis = wd.MultiHotkeyListener(object(), hold_key=keyboard.Key.shift_r, toggle_key=keyboard.Key.ctrl_r)
    assert lis.hold_key == keyboard.Key.shift_r
    assert lis.toggle_key == keyboard.Key.ctrl_r


def test_multi_listener_defaults():
    wd = _load()
    lis = wd.MultiHotkeyListener(object())
    assert lis.hold_key == keyboard.Key.alt_r
    assert lis.toggle_key == keyboard.Key.cmd_r
```

- [ ] **Step 2: 실패 확인** — TypeError(키워드 인자 미지원).

- [ ] **Step 3: 구현** — `MultiHotkeyListener.__init__` 교체:

```python
    def __init__(self, app, hold_key=keyboard.Key.alt_r, toggle_key=keyboard.Key.cmd_r):
        self.app = app
        self.hold_key = hold_key
        self.toggle_key = toggle_key
        self.active_trigger = None  # None | "hold" | "toggle"
```

- [ ] **Step 4: 통과 + 회귀** — `./venv/bin/python -m pytest -q` 통과.

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py test_hotkey_config.py
git commit -m "feat: MultiHotkeyListener accepts hold_key/toggle_key args"
```

## Task C3: 설정에 hotkey 필드 추가

**Files:**
- Modify: `app_config.py`, `whisper-dictation.py` (`current_config`, `_apply_saved_config`)
- Test: `test_model_size.py` (추가) 또는 `test_hotkey_config.py`

- [ ] **Step 1: 실패 테스트** (`test_hotkey_config.py` 끝):

```python
def test_app_config_has_hotkey_defaults(tmp_path, monkeypatch):
    import app_config
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "config_path", lambda: str(cfg_file))
    cfg = app_config.load_config()
    assert cfg["hotkey_mode"] == "multi"
    assert cfg["hold_key"] == "alt_r"
    assert cfg["toggle_key"] == "cmd_r"
```

- [ ] **Step 2: 실패 확인** — KeyError.

- [ ] **Step 3: 구현**

(a) `app_config.py` DEFAULTS 에 추가:
```python
    "hotkey_mode": "multi",
    "hold_key": "alt_r",
    "toggle_key": "cmd_r",
```

(b) `whisper-dictation.py` `current_config()` 의 반환 dict 에 추가(다른 키들 옆):
```python
            "hotkey_mode": getattr(self, "hotkey_mode", "multi"),
            "hold_key": getattr(self, "hold_key", "alt_r"),
            "toggle_key": getattr(self, "toggle_key", "cmd_r"),
```

(c) `_apply_saved_config()` 끝(`self.sync_menu_state()` 앞)에 추가:
```python
        self.hotkey_mode = cfg["hotkey_mode"]
        self.hold_key = cfg["hold_key"]
        self.toggle_key = cfg["toggle_key"]
```

- [ ] **Step 4: 통과 + 회귀** — `./venv/bin/python -m pytest -q` 통과.

- [ ] **Step 5: 커밋**

```bash
git add app_config.py whisper-dictation.py test_hotkey_config.py
git commit -m "feat: persist hotkey_mode/hold_key/toggle_key in config"
```

## Task C4: apply_hotkey_config — 리스너 빌드/스왑

**Files:**
- Modify: `whisper-dictation.py` (`StatusBarApp` 메서드 추가, `main` 단순화)
- Test: `test_hotkey_config.py` (build 선택 로직)

- [ ] **Step 1: 실패 테스트 추가** — `build_key_listener` 가 모드별 올바른 타입을 만드는지(FakeApp 으로):

```python
def test_build_key_listener_selects_type():
    wd = _load()

    class A:
        hotkey_mode = "multi"
        hold_key = "shift_r"
        toggle_key = "cmd_r"
        key_combination = "cmd_l+alt"
    a = A()
    a.build_key_listener = wd.StatusBarApp.build_key_listener.__get__(a, A)
    kl = a.build_key_listener()
    assert isinstance(kl, wd.MultiHotkeyListener)
    assert kl.hold_key == keyboard.Key.shift_r

    a.hotkey_mode = "double"
    assert isinstance(a.build_key_listener(), wd.DoubleCommandKeyListener)

    a.hotkey_mode = "single"
    assert isinstance(a.build_key_listener(), wd.GlobalKeyListener)
```

- [ ] **Step 2: 실패 확인** — AttributeError(`build_key_listener` 없음).

- [ ] **Step 3: 구현**

(a) `StatusBarApp` 에 메서드 추가(`resolve_review` 아래쯤):
```python
    def build_key_listener(self):
        mode = getattr(self, "hotkey_mode", "multi")
        if mode == "double":
            return DoubleCommandKeyListener(self)
        if mode == "single":
            return GlobalKeyListener(self, getattr(self, "key_combination", "cmd_l+alt"))
        return MultiHotkeyListener(
            self,
            hold_key=key_from_name(getattr(self, "hold_key", "alt_r")),
            toggle_key=key_from_name(getattr(self, "toggle_key", "cmd_r")),
        )

    def apply_hotkey_config(self):
        """현재 설정으로 전역 단축키 리스너를 (재)구성한다. 즉시 적용."""
        old = getattr(self, "_global_listener", None)
        if old is not None:
            try:
                old.stop()
            except Exception:
                pass
        key_listener = self.build_key_listener()
        self._key_listener = key_listener

        def on_review_or_hotkey(key):
            if self.review_active:
                toggle_key = getattr(key_listener, "toggle_key", None)
                action = decide_review_action(key, toggle_key=toggle_key)
                if action is not None:
                    self._review_suppress = True
                    self.resolve_review(action)
                return
            key_listener.on_key_press(key)

        def suppress_review_key(event_type, event):
            if getattr(self, "_review_suppress", False):
                self._review_suppress = False
                return None
            return event

        self._global_listener = keyboard.Listener(
            on_press=on_review_or_hotkey,
            on_release=key_listener.on_key_release,
            darwin_intercept=suppress_review_key,
        )
        self._global_listener.start()
```

(b) `__init__` 에 `self.key_combination = "cmd_l+alt"` 초기화 추가(다른 상태 옆). `_apply_saved_config` 가 hotkey_mode/keys 를 채우므로 apply 는 main 에서.

(c) `main()` 의 라인 706-738(키리스너 분기 + 래퍼 + listener.start) 전체를 다음으로 교체:
```python
    # CLI 플래그가 있으면 이번 실행에 한해 설정을 덮어쓴다(없으면 저장된 설정 사용).
    if args.k_double_cmd or args.hotkeys == "double":
        app.hotkey_mode = "double"
    elif args.hotkeys == "single":
        app.hotkey_mode = "single"
        app.key_combination = args.key_combination
    elif args.hotkeys == "multi":
        app.hotkey_mode = "multi"
    app.apply_hotkey_config()
```

(d) `parse_args` 의 `--hotkeys` 기본을 `None` 으로 바꿔 "미지정 시 저장된 설정 사용" 이 되게:
```python
    parser.add_argument("--hotkeys", choices=("multi", "single", "double"), default=None,
                        help="multi=right Option(hold)/right Cmd(toggle) (default from settings); single=-k combo; double=double right Cmd.")
```
그리고 위 (c) 의 분기에 맞춰: `args.hotkeys == "multi"` 는 명시했을 때만 True(None 이면 저장값 유지).

- [ ] **Step 4: 통과 + 회귀** — `./venv/bin/python -m py_compile whisper-dictation.py` 후 `./venv/bin/python -m pytest -q` 통과. 추가 점검: 리스너 스왑이 예외 없이 되는지 가벼운 스모크(메인스레드 필요 없는 부분만) — 생략 가능, 실동작은 사용자 실행.

- [ ] **Step 5: 커밋**

```bash
git add whisper-dictation.py test_hotkey_config.py
git commit -m "feat: StatusBarApp.apply_hotkey_config builds/swaps global listener; main uses it"
```

## Task C5: 대시보드에서 단축키 설정

**Files:**
- Modify: `dashboard.py` (config GET/POST), `templates/dashboard.html`
- Test: `test_hotkey_config.py` (API)

- [ ] **Step 1: 실패 테스트 추가** — POST 가 검증·저장·적용을 부르는지(FakeApp):

```python
def test_api_config_sets_and_applies_hotkeys(monkeypatch):
    import dashboard

    class FakeApp:
        mode = "streaming"
        current_language = "ko"
        languages = ["ko", "en"]
        k_double_cmd = False
        selected_model = "1.7b"
        stream_interval = 1.2
        max_time = 0
        started = False
        hotkey_mode = "multi"
        hold_key = "alt_r"
        toggle_key = "cmd_r"
        applied = 0
        saved = 0
        def save_settings(self): self.saved += 1
        def apply_hotkey_config(self): self.applied += 1
        def sync_menu_state(self): pass
    fake = FakeApp()
    dashboard.app_instance = fake
    client = dashboard.flask_app.test_client()

    r = client.post("/api/config", json={"hotkey_mode": "multi", "hold_key": "shift_r", "toggle_key": "cmd_r"})
    assert r.status_code == 200
    assert fake.hold_key == "shift_r"
    assert fake.applied == 1

    # 같은 키면 400 + 미적용
    before = fake.applied
    r2 = client.post("/api/config", json={"hotkey_mode": "multi", "hold_key": "cmd_r", "toggle_key": "cmd_r"})
    assert r2.status_code == 400
    assert fake.applied == before
```

- [ ] **Step 2: 실패 확인** — hotkey 미처리로 FAIL.

- [ ] **Step 3: 구현**

(a) `dashboard.py` GET(`get_config`) 반환에 추가:
```python
        "hotkey_mode": getattr(app_instance, "hotkey_mode", "multi"),
        "hold_key": getattr(app_instance, "hold_key", "alt_r"),
        "toggle_key": getattr(app_instance, "toggle_key", "cmd_r"),
```

(b) `dashboard.py` 상단에 `import whisper_dictation`은 불가(하이픈) → 검증 함수는 importlib 부담이 크므로, **검증을 dashboard 안에서 직접** 수행한다. `post_config` 의 `save_settings` 호출 직전에 추가:
```python
    hotkey_changed = any(k in data for k in ("hotkey_mode", "hold_key", "toggle_key"))
    if hotkey_changed:
        mode = data.get("hotkey_mode", getattr(app_instance, "hotkey_mode", "multi"))
        hold = data.get("hold_key", getattr(app_instance, "hold_key", "alt_r"))
        toggle = data.get("toggle_key", getattr(app_instance, "toggle_key", "cmd_r"))
        valid_keys = ("alt_r", "cmd_r", "ctrl_r", "shift_r")
        if mode not in ("multi", "single", "double"):
            return jsonify({"error": "unknown hotkey mode"}), 400
        if mode == "multi" and (hold == toggle or hold not in valid_keys or toggle not in valid_keys):
            return jsonify({"error": "hold/toggle keys must differ and be valid"}), 400
        app_instance.hotkey_mode = mode
        app_instance.hold_key = hold
        app_instance.toggle_key = toggle
```
그리고 `save_settings` 호출 다음에:
```python
    if hotkey_changed and hasattr(app_instance, "apply_hotkey_config"):
        app_instance.apply_hotkey_config()
```
(주의: 검증 로직이 C1 의 `validate_hotkey_config` 와 의미가 같아야 한다 — 둘 다 "multi 에서 hold==toggle 거부". 키 목록은 위 4종.)

(c) `templates/dashboard.html` 에 단축키 섹션 추가(모델/언어 근처):
```html
                <h2>단축키</h2>
                <label for="hotkey-mode">방식</label>
                <select id="hotkey-mode" onchange="onHotkeyModeChange()">
                    <option value="multi">오른쪽 Option 꾹 + 오른쪽 Cmd 토글</option>
                    <option value="single">조합키(실행 옵션)</option>
                    <option value="double">오른쪽 Cmd 더블탭</option>
                </select>
                <div id="multi-keys">
                    <label for="hold-key">짧은 말(꾹누르기) 키</label>
                    <select id="hold-key">
                        <option value="alt_r">오른쪽 Option</option>
                        <option value="cmd_r">오른쪽 Cmd</option>
                        <option value="ctrl_r">오른쪽 Ctrl</option>
                        <option value="shift_r">오른쪽 Shift</option>
                    </select>
                    <label for="toggle-key">긴 말(토글) 키</label>
                    <select id="toggle-key">
                        <option value="alt_r">오른쪽 Option</option>
                        <option value="cmd_r">오른쪽 Cmd</option>
                        <option value="ctrl_r">오른쪽 Ctrl</option>
                        <option value="shift_r">오른쪽 Shift</option>
                    </select>
                </div>
                <button onclick="saveHotkeys()">단축키 저장</button>
                <p id="hotkey-msg" class="hint"></p>
```

(d) JS 추가:
```javascript
        function onHotkeyModeChange() {
            const mode = document.getElementById("hotkey-mode").value;
            document.getElementById("multi-keys").style.display = (mode === "multi") ? "" : "none";
        }

        function saveHotkeys() {
            const mode = document.getElementById("hotkey-mode").value;
            const hold = document.getElementById("hold-key").value;
            const toggle = document.getElementById("toggle-key").value;
            const msg = document.getElementById("hotkey-msg");
            if (mode === "multi" && hold === toggle) {
                msg.textContent = "꾹누르기 키와 토글 키는 서로 달라야 합니다.";
                return;
            }
            fetch("/api/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ hotkey_mode: mode, hold_key: hold, toggle_key: toggle }),
            })
            .then(r => r.json().then(j => ({ ok: r.ok, j })))
            .then(({ ok, j }) => { msg.textContent = ok ? "저장됨 — 바로 적용됩니다." : ("오류: " + (j.error || "")); });
        }
```
그리고 `DOMContentLoaded` 의 config fetch 콜백에 채우기 추가:
```javascript
                    document.getElementById("hotkey-mode").value = data.hotkey_mode || "multi";
                    document.getElementById("hold-key").value = data.hold_key || "alt_r";
                    document.getElementById("toggle-key").value = data.toggle_key || "cmd_r";
                    onHotkeyModeChange();
```

- [ ] **Step 4: 통과 + 회귀** — `./venv/bin/python -m py_compile dashboard.py` 후 `./venv/bin/python -m pytest -q` 통과.

- [ ] **Step 5: 커밋**

```bash
git add dashboard.py templates/dashboard.html test_hotkey_config.py
git commit -m "feat: dashboard hotkey settings (mode + keys), validated, applied at runtime"
```

## Task C6: .app 재빌드 + 실행 점검 + 문서

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: 재빌드** — `bash build_app.sh 2>&1 | tail -15` → `dist/Qwen Dictation.app` 재생성, 치명적 에러 없음.

- [ ] **Step 2: 번들 실행 점검**
```bash
pkill -f "Qwen Dictation.app/Contents/MacOS" 2>/dev/null; sleep 1
( "dist/Qwen Dictation.app/Contents/MacOS/Qwen Dictation" > /tmp/qwen_cfg_run.log 2>&1 & P=$!; sleep 35; kill $P 2>/dev/null )
grep -iE "error|traceback|no module|vocabulary|Dashboard|Initializing" /tmp/qwen_cfg_run.log | head -20
pkill -f "Qwen Dictation.app/Contents/MacOS" 2>/dev/null || true
```
Expected: traceback 없음, Dashboard 시작 로그.

- [ ] **Step 3: README/CLAUDE.md 갱신** — 모델은 1.7b만, 사전 대신 "단어 등록", 단축키 대시보드 설정 가능을 반영.

- [ ] **Step 4: 커밋**
```bash
git add README.md CLAUDE.md
git commit -m "docs: 1.7b-only model, word-registration vocabulary, configurable hotkeys"
```

- [ ] **Step 5: 사용자 실사용 안내(자동화 불가)**
> 새 앱 우클릭→열기. 대시보드(127.0.0.1:5001)에서 ①단어 등록에 자주 쓰는 용어 넣기 ②단축키 방식·키 바꿔보고 바로 적용되는지 ③긴 말 받아쓰고 패널에서 토글키/Tab/Esc 확인.

---

## Self-Review (작성자 점검)

**1. 스펙 커버리지:** A(0.6b 제거: UI 옵션·JS·dashboard 기본·CLI choices·get_model·transcribe 기본·stale 보정 ✓), B(vocabulary 모듈·context 전달·apply_dictionary 제거·API·UI·migration ✓), C(키매핑/검증·리스너 인자화·config 저장·apply_hotkey_config 스왑·대시보드 UI/적용 ✓).

**2. 플레이스홀더:** 모든 코드 스텝 실제 코드. UI(B4/C5) 는 헤드리스 단위테스트 불가 → 페이지 로드/사용자 실행으로 명시.

**3. 타입/이름 일치:** `vocabulary.load_vocabulary/save_vocabulary/build_context/ensure_vocabulary`(B1→B2/B3 사용), `app_paths.vocabulary_path`(B1→전역), `key_from_name/validate_hotkey_config/HOTKEY_KEY_NAMES/HOTKEY_MODES`(C1→C4), `MultiHotkeyListener(hold_key,toggle_key)`(C2→C4 `build_key_listener`), `hotkey_mode/hold_key/toggle_key`(C3 config↔current_config↔apply), `apply_hotkey_config/build_key_listener/_global_listener/_key_listener`(C4→C5 호출). dashboard 검증 로직은 C1 `validate_hotkey_config` 와 의미 동일(중복이지만 하이픈 모듈 import 회피 — 의도적).

**알려진 한계:** ①단어 등록(context)은 확정 치환이 아니라 인식 편향 — 고집스런 오인식은 가끔 샐 수 있음(사용자 합의됨). ②AppKit/전역키/실제 받아쓰기/대시보드 동작은 헤드리스 검증 불가 → 순수 로직만 단위테스트, 나머지는 .app 실행+사용자 실사용. ③single 모드의 조합키는 대시보드에서 키 선택 안 함(실행 옵션 `-k` 로만) — multi 가 기본·주력이라 YAGNI.
