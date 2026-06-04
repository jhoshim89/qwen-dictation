# ASR Domain-Context Framing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user bias Qwen3-ASR toward their professional domain (veterinary ophthalmology) by feeding a freeform "domain context" sentence — e.g. `"수의안과 진료. 안과 질환과 검사 용어 위주"` — to the model on every transcription, in addition to the existing registered-word list.

**Architecture:** Qwen3-ASR's `model.transcribe(context=...)` accepts an arbitrary string (not just a word list). We add a user-editable `domain_context` setting, persist it in `config.json`, and prepend it to the comma-joined vocabulary terms inside `vocabulary.build_context`. The transcriber reads it the same way it already reads `min_volume` (pushed from the app each streaming tick). A small domain-echo guard re-transcribes without context if the model parrots the domain sentence back. The dashboard gets a one-line field to edit it live.

**Tech Stack:** Python 3.11, Qwen3-ASR (`qwen_asr`), Flask dashboard, pytest. Target branch: `feat/bottom-overlay` (the live-streaming version the user actually runs; the music-pause WIP is parked in `git stash@{0}` on `main`).

**Why a rebuild is needed:** The running app is a frozen PyInstaller `.app`. The *code* change (Tasks 1–5) requires one rebuild (Task 6) to take effect. After that, the *value* of `domain_context` lives in `config.json` and is editable from the dashboard with no further rebuild.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `vocabulary.py` | Build the ASR context string | Modify `build_context` to take a `domain` prefix |
| `app_config.py` | Persist live settings to `config.json` | Add `domain_context` default |
| `whisper-dictation.py` | Transcriber + app settings wiring | Read domain in `transcribe_file`, add domain-echo guard, push from app, include in save/load |
| `dashboard.py` | Settings HTTP API | Return/accept `domain_context` |
| `templates/dashboard.html` | Settings UI | One-line "분야 설명" field wired to `updateConfig()` |
| `test_vocabulary.py` | Unit tests for context building | Add domain cases |
| `test_app_config.py` | Unit tests for config | Add domain default/roundtrip; fix the exact-keys test |
| `test_transcribe_context.py` | Unit tests for transcriber context | Add domain-prepend, domain-echo, app-save cases |

---

## Task 1: `build_context` accepts a domain prefix

**Files:**
- Modify: `vocabulary.py` (function `build_context`, currently lines 48–51)
- Test: `test_vocabulary.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_vocabulary.py`:

```python
def test_build_context_with_domain():
    assert vocabulary.build_context(["각막", "궤양"], domain="수의안과 진료") == "수의안과 진료, 각막, 궤양"


def test_build_context_domain_only():
    assert vocabulary.build_context([], domain="수의안과 진료") == "수의안과 진료"


def test_build_context_blank_domain_is_backward_compatible():
    assert vocabulary.build_context(["각막", "궤양"], domain="   ") == "각막, 궤양"
    assert vocabulary.build_context(["각막", "궤양"]) == "각막, 궤양"


def test_build_context_domain_not_counted_in_term_limit():
    words = [f"w{i}" for i in range(40)]
    terms = vocabulary.build_context(words, domain="DOM").split(", ")
    assert terms[0] == "DOM"
    assert len(terms) == vocabulary.MAX_CONTEXT_TERMS + 1   # domain + 24 terms
    assert terms[1] == "w0" and terms[-1] == "w23"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/pytest test_vocabulary.py -q`
Expected: FAIL — `build_context()` got an unexpected keyword argument `'domain'`.

- [ ] **Step 3: Implement the domain prefix**

Replace `build_context` in `vocabulary.py` (lines 48–51) with:

```python
def build_context(words, domain="", limit=MAX_CONTEXT_TERMS):
    """단어 목록 → model.transcribe 의 context 문자열.

    domain 이 있으면 분야 머리말로 맨 앞에 붙여 모델을 그 분야로 편향한다(예:
    "수의안과 진료"). 단어는 앞에서부터 limit 개만 쓴다 — domain 은 그 한도에
    포함되지 않는다. domain 이 비면 기존과 동일하게 단어 목록만 반환한다.
    """
    domain = str(domain).strip()
    terms = [w for w in words if w]
    parts = ([domain] if domain else []) + terms[:limit]
    return ", ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest test_vocabulary.py -q`
Expected: PASS (new cases + the existing `test_build_context` / `test_build_context_caps_term_count` still pass).

- [ ] **Step 5: Commit**

```bash
git add vocabulary.py test_vocabulary.py
git commit -m "feat: build_context accepts optional domain prefix"
```

---

## Task 2: `domain_context` default in config

**Files:**
- Modify: `app_config.py` (`DEFAULTS`, lines 12–25)
- Test: `test_app_config.py` (add cases AND fix `test_defaults_only_have_live_settings`)

- [ ] **Step 1: Write/adjust the failing tests**

In `test_app_config.py`, update `test_defaults_only_have_live_settings` to include the new key:

```python
def test_defaults_only_have_live_settings():
    assert set(app_config.DEFAULTS) == {
        "language", "max_time", "input_device", "hold_key", "toggle_key",
        "min_volume", "edit_interrupt_mode", "max_time_zero_migrated",
        "hold_send_enter", "domain_context",
    }
    assert app_config.DEFAULTS["max_time"] == 300
    assert app_config.DEFAULTS["min_volume"] == 35
    assert app_config.DEFAULTS["edit_interrupt_mode"] == "continue"
    assert app_config.DEFAULTS["hold_send_enter"] is True
    assert app_config.DEFAULTS["domain_context"] == ""
```

Append two new tests:

```python
def test_domain_context_defaults_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "config_path", lambda: str(tmp_path / "config.json"))
    assert app_config.load_config()["domain_context"] == ""


def test_domain_context_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "config_path", lambda: str(tmp_path / "config.json"))
    app_config.save_config({"domain_context": "수의안과 진료"})
    assert app_config.load_config()["domain_context"] == "수의안과 진료"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/pytest test_app_config.py -q`
Expected: FAIL — `test_defaults_only_have_live_settings` set mismatch and `KeyError: 'domain_context'`.

- [ ] **Step 3: Add the default**

In `app_config.py` `DEFAULTS`, add the key right after `"hold_send_enter": True,` (before `"max_time_zero_migrated"`):

```python
    # 홀드 키를 떼면 마지막 글자까지 입력한 뒤 자동으로 Enter 를 보낼지.
    "hold_send_enter": True,
    # 받아쓰기 분야 머리말(자유 문장). 매 변환의 context 앞에 붙어 모델을 그 분야로
    # 편향한다. 예: "수의안과 진료. 안과 질환과 검사 용어 위주". 빈 문자열이면 미사용.
    "domain_context": "",
    "max_time_zero_migrated": True,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest test_app_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app_config.py test_app_config.py
git commit -m "feat: add domain_context live setting (default empty)"
```

---

## Task 3: Transcriber prepends domain context + domain-echo guard

**Files:**
- Modify: `whisper-dictation.py` (add `looks_like_domain_echo` near `looks_like_vocab_echo`; edit `SpeechTranscriber.transcribe_file`, lines 329–352)
- Test: `test_transcribe_context.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_transcribe_context.py`:

```python
def test_transcribe_prepends_domain_context(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["녹내장"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(7).randn(16000) * 5000))

    tr = wd.SpeechTranscriber("cpu", None)
    tr.domain_context = "수의안과 진료"
    fake = _FakeModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)

    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "녹음 결과"
    assert fake.calls[0]["context"] == "수의안과 진료, 녹내장"


def test_looks_like_domain_echo():
    wd = _load()
    assert wd.looks_like_domain_echo("수의안과 진료", "수의안과 진료.") is True
    assert wd.looks_like_domain_echo("녹내장입니다", "수의안과 진료") is False
    assert wd.looks_like_domain_echo("anything", "") is False
    assert wd.looks_like_domain_echo("", "수의안과 진료") is False


def test_domain_echo_retranscribes_without_context(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["녹내장"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(8).randn(16000) * 5000))

    class EchoDomainModel:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio, context="", language=None, **kw):
            self.calls.append(context)
            # context 있으면 분야 머리말을 그대로 뱉음(echo), 없으면 진짜
            return [_FakeResult("수의안과 진료" if context else "녹내장입니다")]

    tr = wd.SpeechTranscriber("cpu", None)
    tr.domain_context = "수의안과 진료"
    fake = EchoDomainModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)

    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "녹내장입니다"
    assert fake.calls[0] != "" and fake.calls[1] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/pytest test_transcribe_context.py -q`
Expected: FAIL — `looks_like_domain_echo` not defined; context lacks the domain prefix.

- [ ] **Step 3: Add `looks_like_domain_echo`**

In `whisper-dictation.py`, immediately AFTER the `looks_like_vocab_echo` function (which ends just before `def looks_like_repetition_hallucination`), add:

```python
def looks_like_domain_echo(text, domain):
    """결과가 분야 머리말(domain)을 거의 그대로 뱉은 것이면 context 환각으로 본다.

    공백·구두점을 무시하고 비교한다. domain 이 비었거나 text 가 비면 False.
    """
    domain = str(domain).strip()
    if not domain or not str(text).strip():
        return False
    strip_re = r"[\s,.;!?·]+"
    norm_text = re.sub(strip_re, "", str(text)).lower()
    norm_domain = re.sub(strip_re, "", domain).lower()
    return norm_text == norm_domain
```

(`re` is already imported at the top of `whisper-dictation.py`.)

- [ ] **Step 4: Wire domain into `transcribe_file`**

Replace the body of `transcribe_file` from the `vocab = ...` line through the `return text` (lines 341–352) with:

```python
        vocab = vocabulary.load_vocabulary()
        domain = getattr(self, "domain_context", "")
        # 분명한 말소리일 때만 등록 단어/분야 머리말로 편향한다(약하면 context 비워 echo 차단).
        context = vocabulary.build_context(vocab, domain) if peak >= speech_threshold else ""
        results = model.transcribe(audio_path, context=context, language=language)
        if not results:
            return ""
        text = results[0].text.strip()
        # context 환각(등록 단어만 / 분야 머리말 그대로) 의심 시 → context 없이 재전사.
        if context and (looks_like_vocab_echo(text, vocab) or looks_like_domain_echo(text, domain)):
            plain = model.transcribe(audio_path, context="", language=language)
            text = plain[0].text.strip() if plain else ""
        return text
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/bin/pytest test_transcribe_context.py -q`
Expected: PASS (new cases + all existing context tests, including `test_transcribe_drops_context_on_weak_audio`, still pass).

- [ ] **Step 6: Commit**

```bash
git add whisper-dictation.py test_transcribe_context.py
git commit -m "feat: transcriber prepends domain context with echo guard"
```

---

## Task 4: App persists + pushes `domain_context`

**Files:**
- Modify: `whisper-dictation.py` — `current_config` (lines 726–736), `_apply_saved_config` (lines 765–778), and the streaming-tick push (lines 495–497)
- Test: `test_transcribe_context.py`

- [ ] **Step 1: Write the failing test**

Append to `test_transcribe_context.py`:

```python
def test_current_config_includes_domain_context():
    import types
    wd = _load()
    stub = types.SimpleNamespace(
        current_language="ko", max_time=300, input_device="",
        hold_key="cmd_r", toggle_key="alt_r", min_volume=35,
        edit_interrupt_mode="stop", hold_send_enter=True,
        domain_context="수의안과 진료",
    )
    cfg = wd.StatusBarApp.current_config(stub)
    assert cfg["domain_context"] == "수의안과 진료"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest test_transcribe_context.py::test_current_config_includes_domain_context -q`
Expected: FAIL — `KeyError: 'domain_context'`.

- [ ] **Step 3a: Include in `current_config`**

In `current_config` (lines 727–736), add after the `"hold_send_enter"` line:

```python
            "hold_send_enter": getattr(self, "hold_send_enter", True),
            "domain_context": getattr(self, "domain_context", ""),
        }
```

- [ ] **Step 3b: Load in `_apply_saved_config`**

In `_apply_saved_config`, after the `self.hold_send_enter = ...` line (line 775) and before the `if getattr(self, "recorder", None) ...` block, add:

```python
        self.hold_send_enter = bool(cfg.get("hold_send_enter", True))
        self.domain_context = str(cfg.get("domain_context", "") or "")
        if getattr(self, "recorder", None) is not None:
            self.recorder.transcriber.min_volume = self.min_volume
            self.recorder.transcriber.domain_context = self.domain_context
        self.sync_menu_state()
```

- [ ] **Step 3c: Push every streaming tick (mirror `min_volume`)**

In the streaming tick (lines 495–497), right after the `self.transcriber.min_volume = normalize_min_volume(...)` assignment, add:

```python
        self.transcriber.min_volume = normalize_min_volume(
            getattr(self.app, "min_volume", DEFAULT_MIN_VOLUME)
        )
        self.transcriber.domain_context = getattr(self.app, "domain_context", "")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest -q`
Expected: PASS (full suite — 119 prior tests + the new ones).

- [ ] **Step 5: Commit**

```bash
git add whisper-dictation.py test_transcribe_context.py
git commit -m "feat: persist and push domain_context from app to transcriber"
```

---

## Task 5: Dashboard exposes `domain_context`

**Files:**
- Modify: `dashboard.py` — `get_config` return dict, and `post_config`'s `apply()`
- Modify: `templates/dashboard.html` — add field + JS wiring
- Verify: curl against the running server (no unit test; Flask glue mirrors `min_volume` exactly)

- [ ] **Step 1: Return it from `get_config`**

In `dashboard.py` `get_config`, add to the returned dict after the `"hold_send_enter"` line:

```python
        "hold_send_enter": bool(getattr(app_instance, 'hold_send_enter', True)),
        "domain_context": getattr(app_instance, 'domain_context', ''),
    })
```

- [ ] **Step 2: Accept it in `post_config`'s `apply()`**

In `dashboard.py` `post_config`, inside `apply()`, after the `min_volume` block (the one that sets `app_instance.recorder.transcriber.min_volume`), add:

```python
        if 'domain_context' in data:
            app_instance.domain_context = str(data['domain_context'] or "")
            if getattr(app_instance, "recorder", None) is not None:
                app_instance.recorder.transcriber.domain_context = app_instance.domain_context
```

- [ ] **Step 3: Add the UI field**

In `templates/dashboard.html`, the vocab pane body begins with
`<div class="panel-body"><textarea id="vocab-list" ...></textarea>`.
Insert a labeled field immediately BEFORE that `<textarea>`:

```html
<div class="panel-body"><label for="domain-context">분야 (받아쓰기 도메인)</label><input id="domain-context" type="text" placeholder="예: 수의안과 진료. 안과 질환과 검사 용어 위주" onchange="updateConfig()"><p class="hint">받아쓸 때마다 이 문장을 모델에 함께 알려 그 분야로 인식을 기울입니다. 비워두면 사용하지 않습니다.</p><textarea id="vocab-list" placeholder="예:&#10;Qwen&#10;각막궤양&#10;심재호"></textarea>
```

- [ ] **Step 4: Wire it in JS**

In `templates/dashboard.html` `fetchConfig(...)`, add after the `hold-send-enter` value is set:

```javascript
document.getElementById("domain-context").value=d.domain_context||"";
```

In `updateConfig()`, add `domain_context` to the POST body object:

```javascript
,hold_send_enter:document.getElementById("hold-send-enter").value==="on",domain_context:document.getElementById("domain-context").value})})
```

(Add `,domain_context:document.getElementById("domain-context").value` to the existing `JSON.stringify({...})` payload — do not remove existing keys.)

- [ ] **Step 5: Verify compile + tests still green**

Run: `./venv/bin/python -m py_compile dashboard.py && ./venv/bin/pytest -q`
Expected: compile OK; full suite PASS.

- [ ] **Step 6: Commit**

```bash
git add dashboard.py templates/dashboard.html
git commit -m "feat: dashboard field to edit ASR domain context"
```

---

## Task 6: Rebuild, seed vocabulary, verify end-to-end (empirical)

**Files:** none (build + runtime verification). This is the real proof — do not declare success on tests alone.

- [ ] **Step 1: Rebuild the signed .app**

```bash
./build_app.sh > /tmp/qwen_build.log 2>&1; tail -4 /tmp/qwen_build.log
```
Expected: `BUILD OK -> dist/Qwen Dictation.app` and `Signing with stable identity: Qwen Dictation Local Signing`.

- [ ] **Step 2: Swap the running app**

```bash
pkill -f "whisper-dictation.py"; pkill -f "Qwen Dictation.app/Contents/MacOS"; sleep 1
open "dist/Qwen Dictation.app"
for i in $(seq 1 25); do curl -s --max-time 3 http://127.0.0.1:5001/api/status >/dev/null 2>&1 && { echo "up"; break; }; sleep 3; done
```
Expected: `up`.

- [ ] **Step 3: Set the domain context + seed key terms** (CONFIRM the term list with the user first — domain content is their call)

```bash
curl -s -X POST http://127.0.0.1:5001/api/config -H "Content-Type: application/json" \
  -d '{"domain_context":"수의안과 진료. 안과 질환과 검사 용어 위주"}' >/dev/null
curl -s -X POST http://127.0.0.1:5001/api/vocabulary -H "Content-Type: application/json" \
  -d '["녹내장","각막궤양","포도막염","안검내반","유루증","건성각결막염","체리아이","각막부종","진행성망막위축","안압","쉬르머검사","플루오레세인염색"]' >/dev/null
curl -s http://127.0.0.1:5001/api/config | python3 -c "import sys,json;print('domain:',json.load(sys.stdin)['domain_context'])"
curl -s http://127.0.0.1:5001/api/vocabulary
```
Expected: domain echoes back; vocabulary shows the 12 terms.

- [ ] **Step 4: Real-speech verification (user-in-the-loop)**

Ask the user to focus a text field, press the hold key, and say **"녹내장"** (and a couple of other seeded terms). Confirm the typed output is correct (`녹내장`, not `높내장`). If a mic/accessibility permission prompt appears on first run, the user approves it once (stable signing keeps it thereafter).
Expected: seeded terms transcribe correctly; non-domain everyday speech is unaffected.

- [ ] **Step 5: Push the branch**

```bash
git push origin feat/bottom-overlay
```

---

## Self-Review Notes

- **Spec coverage:** freeform domain string fed to model (Task 1, 3) ✓; persisted + editable without rebuild after first build (Task 2, 4, 5) ✓; echo safety for the new context (Task 3 domain-echo guard) ✓; weak-audio still drops all context (unchanged guard, covered by existing `test_transcribe_drops_context_on_weak_audio`) ✓; real-world proof (Task 6) ✓.
- **Naming consistency:** `domain_context` used identically across `app_config.DEFAULTS`, `current_config`, `_apply_saved_config`, `SpeechTranscriber.domain_context`, `build_context(domain=...)`, dashboard GET/POST, and the `domain-context` DOM id.
- **Limit semantics:** the domain prefix is intentionally NOT counted against `MAX_CONTEXT_TERMS` (Task 1 test asserts `MAX_CONTEXT_TERMS + 1`), so seeding 24 terms + a domain sentence both fit.
- **Out of scope (YAGNI):** no per-profile domains, no raising `MAX_CONTEXT_TERMS`, no domain-context length cap (kept to a short sentence by UX hint).
