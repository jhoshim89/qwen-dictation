# IME-Safe Dictation Typing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** English (and any non-Hangul) dictation lands as the correct characters even when the macOS input source is Korean, instead of being re-mapped into Hangul jamo (e.g. `hello` → `ㅗ디ㅣㅐ`).

**Architecture:** The streaming path inserts text via `keyboard_controller.type()`, which sends layout-dependent synthetic keystrokes; an active Korean IME re-maps those Latin keys to Hangul. We replace text insertion with `unicode_type()` — a helper that posts CGEvents carrying a Unicode string on keycode 0, which macOS inserts literally, bypassing the keyboard layout and IME. Backspaces and Enter stay as keycode events (already IME-immune). `type_diff` gains an injectable `insert` callable so the behavior is unit-testable and `Recorder._type` can supply the Unicode inserter.

**Tech Stack:** Python 3.11, pynput (existing — backspace/Enter), Quartz/CoreGraphics CGEvents (already a dependency, imported at `whisper-dictation.py:38`), pytest.

**Branch:** `feat/bottom-overlay` (the live-streaming app the user actually runs). Verify with `git rev-parse --abbrev-ref HEAD` before starting.

**Why this is safe:** Inserting via Unicode CGEvents creates no IME composition state, so the existing backspace logic still deletes whole committed characters cleanly. The self-type guard in `_stream_tick` already wraps the insertion call, so synthetic events are not mistaken for manual edits.

---

### Task 1: Spike — confirm Unicode insertion defeats the Korean IME

De-risks the whole plan. The user already confirmed the bug (English → Hangul); this confirms the **fix** before we refactor anything. Throwaway script — not committed.

**Files:**
- Create (throwaway): `/tmp/ime_spike.py`

- [ ] **Step 1: Write the spike script**

```python
# /tmp/ime_spike.py — throwaway. Run, then within 4s click into a text field
# with the macOS input source switched to 한글 (Korean 2-set).
import time
from pynput import keyboard
from Quartz import (
    CGEventCreateKeyboardEvent, CGEventKeyboardSetUnicodeString,
    CGEventPost, kCGHIDEventTap,
)

def unicode_type(text):
    for ch in text:
        down = CGEventCreateKeyboardEvent(None, 0, True)
        CGEventKeyboardSetUnicodeString(down, 1, ch)
        CGEventPost(kCGHIDEventTap, down)
        up = CGEventCreateKeyboardEvent(None, 0, False)
        CGEventKeyboardSetUnicodeString(up, 1, ch)
        CGEventPost(kCGHIDEventTap, up)

print("Focus a Korean-IME text field now...")
time.sleep(4)
keyboard.Controller().type("pynput:hello ")   # expect garbled Hangul
unicode_type("unicode:hello")                 # expect literal 'unicode:hello'
```

- [ ] **Step 2: Run the spike and observe**

Run: `./venv/bin/python /tmp/ime_spike.py`, then click a Korean-IME text field within 4 seconds.
Expected: the `pynput:hello ` portion appears as garbled Hangul (reproduces the bug), and `unicode:hello` appears as literal Latin text (confirms the fix).

- [ ] **Step 3: Decision gate**

If `unicode_type` lands literally → proceed to Task 2 (this plan).
If it does NOT (still garbled) → STOP and report; fall back to the clipboard-paste approach (NSPasteboard set + Cmd+V with save/restore). Do not continue this plan as written.

- [ ] **Step 4: Clean up**

Run: `rm /tmp/ime_spike.py`

---

### Task 2: Make `type_diff` insertion injectable (TDD)

**Files:**
- Modify: `whisper-dictation.py:293-323` (the `type_diff` function)
- Test: `test_streaming.py` (append new tests near the existing `_FakeKeyboard`, ~line 293)

- [ ] **Step 1: Write the failing tests**

Append to `test_streaming.py`:

```python
def test_type_diff_inserts_additions_via_insert_callable():
    wd = _load()
    inserted = []
    kb = _FakeKeyboard()
    result = wd.type_diff("", "hello", kb, insert=inserted.append)
    assert result == "hello"
    assert inserted == ["hello"]
    assert kb.events == []  # pure insertion uses no keystrokes


def test_type_diff_appends_only_the_new_suffix():
    wd = _load()
    inserted = []
    kb = _FakeKeyboard()
    result = wd.type_diff("abc", "abcde", kb, insert=inserted.append)
    assert result == "abcde"
    assert inserted == ["de"]
    assert kb.events == []


def test_type_diff_backspaces_via_keyboard_then_inserts_via_callable():
    wd = _load()
    from pynput import keyboard
    inserted = []
    kb = _FakeKeyboard()
    result = wd.type_diff("abcX", "abcY", kb, insert=inserted.append)
    assert result == "abcY"
    assert inserted == ["Y"]
    assert kb.events.count(("press", keyboard.Key.backspace)) == 1


def test_type_diff_defaults_insert_to_keyboard_type():
    wd = _load()
    typed = []

    class _KbWithType(_FakeKeyboard):
        def type(self, text):
            typed.append(text)

    wd.type_diff("", "hi", _KbWithType())
    assert typed == ["hi"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/pytest test_streaming.py -k "type_diff" -v`
Expected: FAIL — `type_diff()` got an unexpected keyword argument `insert` (and `_FakeKeyboard` has no `.type`).

- [ ] **Step 3: Refactor `type_diff` to take an `insert` callable**

Replace `whisper-dictation.py:293-323` with:

```python
def type_diff(old_text, new_text, keyboard_controller, allow_empty=False, insert=None):
    # `insert(text)` performs the actual character insertion. Default is the
    # pynput controller's keystroke typing, but the streaming path injects an
    # IME-immune Unicode inserter so Latin text isn't remapped to Hangul.
    if insert is None:
        insert = keyboard_controller.type
    old_text = old_text.strip()
    new_text = new_text.strip()
    if not new_text:
        if allow_empty:
            for _ in range(len(old_text)):
                keyboard_controller.press(keyboard.Key.backspace)
                keyboard_controller.release(keyboard.Key.backspace)
            return ""
        return old_text
    if not old_text:
        insert(new_text)
        return new_text
    if new_text.startswith(old_text):
        diff = new_text[len(old_text):]
        if diff:
            insert(diff)
            return new_text
        return old_text

    common_prefix = os.path.commonprefix([old_text, new_text])
    backspaces = len(old_text) - len(common_prefix)
    for _ in range(backspaces):
        keyboard_controller.press(keyboard.Key.backspace)
        keyboard_controller.release(keyboard.Key.backspace)
        time.sleep(0.001)
    diff = new_text[len(common_prefix):]
    if diff:
        insert(diff)
        return new_text
    return old_text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest test_streaming.py -k "type_diff" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `./venv/bin/pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add whisper-dictation.py test_streaming.py
git commit -m "refactor: make type_diff insertion injectable for IME-safe typing"
```

---

### Task 3: Add the `unicode_type` IME-immune inserter (TDD)

**Files:**
- Modify: `whisper-dictation.py:38-46` (extend the existing Quartz import block)
- Modify: `whisper-dictation.py` (add `unicode_type` immediately above `type_diff`, ~line 292)
- Test: `test_streaming.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_streaming.py`:

```python
def test_unicode_type_posts_down_and_up_per_char():
    wd = _load()
    posts = []
    wd.unicode_type("hi", _post=lambda tap, ev: posts.append(ev))
    assert len(posts) == 4  # down+up for 'h', down+up for 'i'


def test_unicode_type_empty_posts_nothing():
    wd = _load()
    posts = []
    wd.unicode_type("", _post=lambda tap, ev: posts.append(ev))
    assert posts == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/pytest test_streaming.py -k "unicode_type" -v`
Expected: FAIL — module `wd` has no attribute `unicode_type`.

- [ ] **Step 3: Extend the Quartz import block**

At `whisper-dictation.py:38-46`, the existing block is:

```python
    from Quartz import (
        CGEventGetFlags,
        kCGEventFlagMaskSecondaryFn,
        kCGEventFlagsChanged,
    )
```
with an `except` that sets `CGEventGetFlags = None` (and constant fallbacks).

Add the four CGEvent symbols to the `try` import and add `None` fallbacks in the `except`:

```python
    from Quartz import (
        CGEventGetFlags,
        kCGEventFlagMaskSecondaryFn,
        kCGEventFlagsChanged,
        CGEventCreateKeyboardEvent,
        CGEventKeyboardSetUnicodeString,
        CGEventPost,
        kCGHIDEventTap,
    )
```

In the matching `except` block, alongside `CGEventGetFlags = None`, add:

```python
    CGEventCreateKeyboardEvent = None
    CGEventKeyboardSetUnicodeString = None
    CGEventPost = None
    kCGHIDEventTap = None
```

- [ ] **Step 4: Add the `unicode_type` helper above `type_diff`**

Insert immediately before `def type_diff(` (~line 292):

```python
def unicode_type(text, _post=None):
    """Insert `text` as literal Unicode via CGEvents (keycode 0 + Unicode string).

    Posting on keycode 0 with the Unicode string set makes macOS insert the
    characters literally, bypassing the active keyboard layout and IME. A Korean
    input source therefore can't remap Latin letters to Hangul, so English
    dictation lands as English. `_post` is injectable for tests.
    """
    post = _post or CGEventPost
    for ch in text:
        down = CGEventCreateKeyboardEvent(None, 0, True)
        CGEventKeyboardSetUnicodeString(down, 1, ch)
        post(kCGHIDEventTap, down)
        up = CGEventCreateKeyboardEvent(None, 0, False)
        CGEventKeyboardSetUnicodeString(up, 1, ch)
        post(kCGHIDEventTap, up)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/bin/pytest test_streaming.py -k "unicode_type" -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Compile + full suite**

Run: `./venv/bin/python -m py_compile whisper-dictation.py && ./venv/bin/pytest -q`
Expected: compile clean, all tests pass.

- [ ] **Step 7: Commit**

```bash
git add whisper-dictation.py test_streaming.py
git commit -m "feat: unicode_type — IME-immune text insertion via CGEvents"
```

---

### Task 4: Wire `Recorder._type` to use the Unicode inserter (TDD)

**Files:**
- Modify: `whisper-dictation.py:482-483` (`Recorder._type`)
- Test: `test_streaming.py`

- [ ] **Step 1: Write the failing test**

Append to `test_streaming.py`:

```python
def test_recorder_type_uses_unicode_inserter(monkeypatch):
    wd = _load()
    captured = {}

    def fake_type_diff(old, new, kb, allow_empty=False, insert=None):
        captured["insert"] = insert
        return new

    monkeypatch.setattr(wd, "type_diff", fake_type_diff)
    rec = _kbd_recorder(wd)
    rec._type("", "hello")
    # When Quartz CGEvents are available, the inserter must be unicode_type.
    # Otherwise _type passes insert=None and type_diff falls back to
    # keyboard_controller.type internally.
    if wd.CGEventCreateKeyboardEvent is not None:
        assert captured["insert"] is wd.unicode_type
    else:
        assert captured["insert"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest test_streaming.py -k "recorder_type_uses_unicode" -v`
Expected: FAIL — `captured["insert"]` is `None` (current `_type` passes no `insert`).

- [ ] **Step 3: Update `Recorder._type`**

Replace `whisper-dictation.py:482-483`:

```python
    def _type(self, old, new):
        return type_diff(old, new, self.transcriber.pykeyboard, allow_empty=True)
```

with:

```python
    def _type(self, old, new):
        # Insert via IME-immune Unicode CGEvents so Latin text isn't remapped to
        # Hangul under a Korean input source; fall back to keystrokes if Quartz
        # CGEvents are unavailable. Backspaces stay as keycodes either way.
        inserter = unicode_type if CGEventCreateKeyboardEvent is not None else None
        return type_diff(old, new, self.transcriber.pykeyboard,
                         allow_empty=True, insert=inserter)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest test_streaming.py -k "recorder_type_uses_unicode" -v`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `./venv/bin/pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add whisper-dictation.py test_streaming.py
git commit -m "feat: stream typing inserts via unicode_type (English under Korean IME)"
```

---

### Task 5: Manual end-to-end verification (the real proof)

Unit tests can't prove IME behavior — this task does. No code; observe real behavior.

**Files:** none.

- [ ] **Step 1: Rebuild the app from this branch**

Run: `./build_app.sh`
Expected: `BUILD OK -> dist/Qwen Dictation.app`, signed with the stable identity.

- [ ] **Step 2: Swap to the new build**

Run: `pkill -f "whisper-dictation.py"; pkill -f "Qwen Dictation.app"; sleep 2; open "dist/Qwen Dictation.app"`
Then wait for the dashboard: `curl -s --max-time 4 http://127.0.0.1:5001/api/status`
Expected: `{"started": false, ...}` within ~10s.

- [ ] **Step 2.5: Smoke-test the engine path**

Run: `curl -s --max-time 120 -X POST http://127.0.0.1:5001/api/selftest -H "Content-Type: application/json" -d '{"seconds":3}'`
Expected: `"ok": true` with a non-zero `peak` (mic capture works on the new build).

- [ ] **Step 3: English-under-Korean-IME test (the bug)**

Switch the macOS input source to **한글**. Focus a plain text field (e.g. TextEdit). Hold the dictation key and say an English phrase ("hello world").
Expected: the field shows `hello world` (literal English), NOT Hangul jamo.

- [ ] **Step 4: Korean no-regression test**

Same input source (한글), dictate a Korean phrase ("녹내장 각막궤양").
Expected: correct Hangul output, same quality as before.

- [ ] **Step 5: Mid-sentence revision test (backspace path)**

Dictate a longer phrase without pausing so the model revises an earlier word.
Expected: the on-screen text corrects itself (backspace + re-insert) and ends correct; no leftover/duplicated characters, no stray Hangul.

- [ ] **Step 6: Manual-edit-guard sanity**

During Step 3, confirm the dictation does not abort treating its own synthetic insertion as a manual edit (`edit_interrupt_mode` is `stop`). If it aborts, the self-type guard around `_stream_tick` insertion needs widening — note and report; do not silently ignore.

- [ ] **Step 7: Record the result**

Report PASS/FAIL per step. If Step 3 fails, the Unicode-insertion assumption was wrong — fall back to clipboard paste (Task 1, Step 3 decision gate).

---

## Out of scope (note, don't silently drop)

- Switching the ASR engine to MLX or C++/GGUF (separate future work — tracked in conversation, not this plan).
- Saving/restoring or otherwise touching the system clipboard (only needed if the clipboard-paste fallback is taken).
- Pushing `main` to the private remote (blocked by default-branch protection; awaiting explicit user OK).
