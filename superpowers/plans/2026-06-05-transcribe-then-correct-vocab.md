# Transcribe-Then-Correct Vocabulary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop registered vocabulary/domain hints from leaking into transcripts ("전문 용어: …" or jargon butting in at weak moments) by never feeding the term list to the model; instead transcribe plain and fix near-miss terms afterward.

**Architecture:** This is the industry-standard approach for local Whisper/Qwen-style dictation apps (MacWhisper, Superwhisper): the model gets **no context prompt**, so it cannot copy the list. A new `term_correct.py` module then scans the plain transcript and replaces spans that sound almost identical to a registered term with the exact term. Korean is compared at the jamo (sound) level via Unicode NFD decomposition; matching uses a similarity threshold (~0.8, "남들 하는 만큼") so ordinary words are not over-corrected. Same-script near-misses only (Korean→Korean, Latin→Latin); cross-script (English term heard as Hangul) is a documented limitation.

**Tech Stack:** Python 3.11, stdlib only (`unicodedata` for jamo decomposition, `difflib.SequenceMatcher` for similarity — both already used in the repo), pytest.

**Aggressiveness decision (user):** "남들 하는 만큼" → industry-typical similarity threshold of `0.8`, applied at word/phrase boundaries, with a short-term guard (skip fuzzy match for terms under ~2 syllables) so a 0.8 match on a tiny word can't fire by accident.

---

## File Structure

- **Create `term_correct.py`** — pure correction logic. One job: given text + term list, return text with near-miss spans replaced by exact terms. No I/O, no app state. Fully unit-testable.
- **Create `test_term_correct.py`** — unit tests for the module.
- **Modify `whisper-dictation.py`**
  - `SpeechTranscriber.transcribe_file` — remove context biasing (always `context=""`); the model transcribes plain.
  - `Recorder._stream_loop` — load the session vocabulary once at start.
  - `Recorder._stream_tick` — apply `term_correct.correct_terms` to the hypothesis before typing.
  - Add `import term_correct` at the top.
- **Modify `test_transcribe_context.py`** — remove the now-obsolete context-biasing / echo integration tests (transcribe_file no longer takes context); keep the pure-function unit tests; add one test asserting transcribe_file passes `context=""`.
- **Modify `test_streaming.py`** — add a test that a misheard term in the live tick gets corrected before typing.

**Left dormant on purpose (not removed in this plan):** `build_context`, `CONTEXT_TERM_LABEL`, `looks_like_vocab_echo`, `looks_like_domain_echo`, `looks_like_context_label_echo`, `vocab_terms_in_text`, and the `domain_context` config field. They become unused once biasing is off. Their isolated unit tests still pass. Removing them + their config/UI plumbing is a low-value follow-up cleanup, kept out of scope here to bound risk.

---

## Task 1: `term_correct` module (TDD)

**Files:**
- Create: `term_correct.py`
- Test: `test_term_correct.py`

- [ ] **Step 1: Write the failing tests**

Create `test_term_correct.py`:

```python
import term_correct


def test_exact_term_is_unchanged():
    assert term_correct.correct_terms("녹내장 환자 봤어", ["녹내장"]) == "녹내장 환자 봤어"


def test_korean_near_miss_replaced_at_jamo_level():
    # 한 음절의 모음만 다른 오인식(계양↔궤양) → 같은 소리로 보고 교정
    assert term_correct.correct_terms("각막계양 소견입니다", ["각막궤양"]) == "각막궤양 소견입니다"


def test_below_threshold_is_left_alone():
    # 전혀 다른 말은 건드리지 않는다(멀쩡한 말 오교체 방지)
    assert term_correct.correct_terms("안녕하세요 반갑습니다", ["각막궤양"]) == "안녕하세요 반갑습니다"


def test_multiword_latin_term_near_miss_replaced():
    assert term_correct.correct_terms(
        "the corneal ulcar healed well", ["corneal ulcer"]
    ) == "the corneal ulcer healed well"


def test_latin_term_case_is_normalized():
    assert term_correct.correct_terms("qwen 좋아", ["Qwen"]) == "Qwen 좋아"


def test_short_term_is_not_fuzzy_matched():
    # 1음절급 짧은 용어는 우연한 0.8 매칭을 막으려 fuzzy 건너뜀(정확히 같을 때만 유지)
    assert term_correct.correct_terms("문을 닫아", ["눈"]) == "문을 닫아"


def test_empty_inputs_are_safe():
    assert term_correct.correct_terms("", ["녹내장"]) == ""
    assert term_correct.correct_terms("녹내장", []) == "녹내장"


def test_cross_script_is_a_known_limitation():
    # 영어 용어가 한글로 들린 경우(큐엔↔Qwen)는 글자체가 달라 교정 못 함(문서화된 한계)
    assert term_correct.correct_terms("큐엔 좋아", ["Qwen"]) == "큐엔 좋아"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/pytest test_term_correct.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'term_correct'`.

- [ ] **Step 3: Write the module**

Create `term_correct.py`:

```python
"""받아쓴 텍스트를 등록 용어로 사후 교정한다.

모델에는 용어 목록을 주지 않으므로(누출 0) 인식은 순수 음향으로만 이뤄지고, 여기서
'소리가 거의 같은' 토막만 등록 용어로 바�throws. 한국어는 NFD 로 음절을 자모로 분해해
소리 단위로 비교한다(게양↔궤양). 같은 글자체 근접 오인식이 대상이며, 교차 글자체
(영어↔한글)는 비교가 불가능해 손대지 않는다(한계).
"""
import re
import unicodedata
from difflib import SequenceMatcher

# "남들 하는 만큼": 유사도가 이 값 이상일 때만 교체한다(멀쩡한 말 오교체 방지).
SIMILARITY_THRESHOLD = 0.8
# 자모로 분해했을 때 이보다 짧은 용어는 fuzzy 매칭하지 않는다(짧으면 우연 매칭 위험).
MIN_NORM_LEN = 4

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _norm(text):
    # NFD: 한글 음절 → 자모(초/중/종성)로 분해. 소리 단위 비교가 되고, 라틴 문자는
    # 소문자화로 대소문자 차이를 흡수한다.
    return unicodedata.normalize("NFD", text).lower()


def _similarity(a, b):
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _replace_spans(text, term, n, threshold):
    """text 안에서 n개 단어로 된 토막이 term 과 임계 이상 비슷하면 term 으로 바꾼다."""
    matches = list(_WORD_RE.finditer(text))
    if len(matches) < n:
        return text
    out = []
    last = 0
    i = 0
    while i <= len(matches) - n:
        span_start = matches[i].start()
        span_end = matches[i + n - 1].end()
        span = text[span_start:span_end]
        if span != term and _similarity(span, term) >= threshold:
            out.append(text[last:span_start])
            out.append(term)
            last = span_end
            i += n
        else:
            i += 1
    out.append(text[last:])
    return "".join(out)


def correct_terms(text, terms, threshold=SIMILARITY_THRESHOLD):
    """text 안의 근접 오인식을 등록 용어로 교정해 돌려준다."""
    if not text or not terms:
        return text
    # 여러 단어로 된 용어를 먼저 맞춘다(부분 매칭이 긴 구를 깨지 않도록).
    ordered = sorted(
        {t.strip() for t in terms if t.strip()},
        key=lambda t: len(t.split()),
        reverse=True,
    )
    result = text
    for term in ordered:
        if len(_norm(term)) < MIN_NORM_LEN:
            continue  # 너무 짧은 용어는 fuzzy 건너뜀
        result = _replace_spans(result, term, len(term.split()), threshold)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest test_term_correct.py -q`
Expected: PASS (8 tests). If `test_korean_near_miss_replaced_at_jamo_level` or the Latin near-miss sits just under 0.8, do NOT loosen blindly — confirm the ratio with `python -c "import term_correct as t; print(t._similarity('각막계양','각막궤양'))"`; the chosen examples are ~0.90, so a failure means a logic bug, not the threshold.

- [ ] **Step 5: Commit**

```bash
git add term_correct.py test_term_correct.py
git commit -m "feat: term_correct — post-transcription jamo-level vocab correction"
```

---

## Task 2: Drop context biasing from `transcribe_file`

**Files:**
- Modify: `whisper-dictation.py` (`SpeechTranscriber.transcribe_file`)
- Test: `test_transcribe_context.py`

- [ ] **Step 1: Update the tests (red)**

In `test_transcribe_context.py`, **delete** these now-obsolete integration tests (they assert context biasing / echo re-transcription, which no longer happens):

- `test_transcribe_passes_vocabulary_context`
- `test_echo_result_retranscribes_without_context`
- `test_transcribe_drops_context_on_weak_audio`
- `test_transcribe_prepends_domain_context`
- `test_domain_echo_retranscribes_without_context`
- `test_domain_leakage_mixed_keeps_vocab`
- `test_unconfirmed_vocab_term_replaced_by_plain`
- `test_confirmed_vocab_term_is_kept`
- `test_labeled_context_echo_dropped_even_with_unknown_terms`

Keep all the pure-function tests (`test_looks_like_vocab_echo`, `test_looks_like_domain_echo*`, `test_looks_like_context_label_echo`, `test_vocab_terms_in_text_finds_mixed_and_glued`, `test_no_apply_dictionary_symbol`, `test_current_config_includes_domain_context`, `test_transcribe_skips_silent_audio`, `test_transcribe_does_not_apply_dictionary_replacements`).

Then **add** this test (asserts the new behavior — no context ever passed):

```python
def test_transcribe_passes_no_context(tmp_path, monkeypatch):
    import numpy as np
    wd = _load()
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr(app_paths, "vocabulary_path", lambda: str(vp))
    vocabulary.save_vocabulary(["각막", "궤양"])
    wav = tmp_path / "speech.wav"
    _write_wav(wav, (np.random.RandomState(1).randn(16000) * 5000))

    tr = wd.SpeechTranscriber("cpu", None)
    tr.domain_context = "수의안과 진료"
    fake = _FakeModel()
    monkeypatch.setattr(tr, "get_model", lambda: fake)

    out = tr.transcribe_file(str(wav), language="Korean")
    assert out == "녹음 결과"
    assert fake.calls[0]["context"] == ""   # 용어/분야를 모델에 주지 않는다(누출 0)
```

- [ ] **Step 2: Run to verify the new test fails**

Run: `./venv/bin/pytest test_transcribe_context.py::test_transcribe_passes_no_context -q`
Expected: FAIL — `assert "전문 용어: 각막, 궤양" == ""` (current code still builds context).

- [ ] **Step 3: Simplify `transcribe_file`**

In `whisper-dictation.py`, replace the entire `transcribe_file` method body with the no-context version:

```python
    def transcribe_file(self, audio_path, language=None):
        # 무음/잡음만 있는 버퍼는 건너뛴다. 용어/분야는 모델에 주지 않는다(context 가
        # 출력에 새는 echo 를 원천 차단). 등록 용어 반영은 받아쓴 뒤 term_correct 가 한다.
        silence_threshold, _ = volume_peak_thresholds(
            getattr(self, "min_volume", DEFAULT_MIN_VOLUME)
        )
        if audio_peak(audio_path) < silence_threshold:
            return ""
        model = self.get_model()
        language = normalize_language(language)
        results = model.transcribe(audio_path, context="", language=language)
        if not results:
            return ""
        return results[0].text.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest test_transcribe_context.py -q`
Expected: PASS (no failures; obsolete tests are gone, new test passes).

- [ ] **Step 5: Commit**

```bash
git add whisper-dictation.py test_transcribe_context.py
git commit -m "refactor: transcribe plain (no vocab/domain context) to kill leakage at source"
```

---

## Task 3: Apply correction in the live streaming tick

**Files:**
- Modify: `whisper-dictation.py` (`import`, `Recorder._stream_loop`, `Recorder._stream_tick`)
- Test: `test_streaming.py`

- [ ] **Step 1: Write the failing test**

Append to `test_streaming.py`:

```python
def test_stream_tick_corrects_misheard_term_before_typing(monkeypatch):
    wd = _load()
    import numpy as np
    rec = _make_recorder(wd, None, ["각막계양 입니다"])   # 모델이 잘못 들은 결과
    rec.session_vocab = ["각막궤양"]                       # 등록 용어
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "각막궤양 입니다"            # 타이핑 전에 교정됨


def test_stream_tick_without_session_vocab_is_unchanged(monkeypatch):
    wd = _load()
    import numpy as np
    rec = _make_recorder(wd, None, ["각막계양 입니다"])
    # session_vocab 미설정 → 교정 없이 그대로
    loud = (np.random.RandomState(0).randn(16000) * 6000).astype(np.int16).tobytes()
    with rec.audio_lock:
        rec.audio_frames = [loud]
    wd.Recorder._stream_tick(rec, language="Korean")
    assert rec.last_typed == "각막계양 입니다"
```

Note: `_make_recorder` builds the recorder via `__new__` and does not set `session_vocab`; `_stream_tick` must read it with a default so the second test (no attribute) is safe.

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest test_streaming.py -k "corrects_misheard or without_session_vocab" -q`
Expected: FAIL — first test types `"각막계양 입니다"` (no correction yet).

- [ ] **Step 3: Add the import**

In `whisper-dictation.py`, add to the local module imports (next to `import vocabulary`):

```python
import term_correct
```

- [ ] **Step 4: Load session vocab once at stream start**

In `Recorder._stream_loop`, just after the existing reset lines, add the vocab load:

```python
    def _stream_loop(self, language):
        self.window_start = 0
        self.committed_text = ""
        self.last_typed = ""
        self.session_vocab = vocabulary.load_vocabulary()
```

- [ ] **Step 5: Apply correction to the hypothesis in `_stream_tick`**

In `Recorder._stream_tick`, after the existing hallucination/punctuation/pause-filler filters and immediately **before** the line that builds `target`, insert the correction:

Find this existing block:

```python
        paused = trailing_silence(window, 16000, silence_threshold, PAUSE_SILENCE_SEC)
        if paused and looks_like_pause_noise_filler(hypo):
            hypo = ""
        # 단위가 붙은 한국어 수사만 아라비아 숫자로 바꾼다('삼 밀리'->3밀리). 변환은
        # idempotent 라 확정 텍스트에 다시 적용해도 안전하다.
        target = text_normalize.normalize_numbers(self.committed_text + hypo)
```

Replace it with (correction added before `target`):

```python
        paused = trailing_silence(window, 16000, silence_threshold, PAUSE_SILENCE_SEC)
        if paused and looks_like_pause_noise_filler(hypo):
            hypo = ""
        # 등록 용어로 사후 교정한다(모델엔 용어를 안 줬으므로 여기서만 반영).
        hypo = term_correct.correct_terms(hypo, getattr(self, "session_vocab", None) or [])
        # 단위가 붙은 한국어 수사만 아라비아 숫자로 바꾼다('삼 밀리'->3밀리). 변환은
        # idempotent 라 확정 텍스트에 다시 적용해도 안전하다.
        target = text_normalize.normalize_numbers(self.committed_text + hypo)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/bin/pytest test_streaming.py -k "corrects_misheard or without_session_vocab" -q`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add whisper-dictation.py test_streaming.py
git commit -m "feat: correct misheard registered terms in the live tick"
```

---

## Task 4: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Compile**

Run: `./venv/bin/python -m py_compile whisper-dictation.py term_correct.py dashboard.py vocabulary.py`
Expected: no output.

- [ ] **Step 2: Full test suite**

Run: `./venv/bin/pytest -q`
Expected: all tests pass.

- [ ] **Step 3: Manual end-to-end (the real proof)**

Restart the app: `pkill -f "whisper-dictation.py"; sleep 1; ./run.sh` (or run the built app).
With a registered term (e.g., `녹내장`, `각막궤양`) in vocabulary, hold-dictate a sentence using that term, including at the very start.
Expected:
- No "전문 용어: …" or out-of-nowhere jargon ever appears (leakage gone — the model isn't given the list).
- A registered term that is slightly misheard lands as the correct term.
- An ordinary sentence with no near-miss is typed unchanged (no false correction).

- [ ] **Step 4: Note the limitation**

Confirm cross-script terms (an English term spoken and heard as Hangul, e.g. "Qwen" → "큐엔") are NOT corrected — this is the documented v1 limitation. If the user needs these, that is a separate follow-up (transliteration-based matching).

---

## Self-Review

- **Spec coverage:** No-context transcription (Task 2) kills leakage at the source; `term_correct` (Task 1) + live wiring (Task 3) reintroduce the registered terms safely; threshold `0.8` + short-term guard encode the "남들 하는 만큼" aggressiveness; jamo (NFD) comparison handles Korean sound-alikes; cross-script limitation is tested and documented. All covered.
- **Placeholder scan:** None — every code/test step has complete code and exact commands.
- **Type consistency:** `correct_terms(text, terms, threshold)` signature is identical across the module, its tests, and the tick call (`term_correct.correct_terms(hypo, session_vocab)`). `session_vocab` is set in `_stream_loop` and read with a safe default in `_stream_tick` and the tests.
- **Dead code:** Listed explicitly under File Structure as intentionally left dormant (out of scope), not silently dropped.
