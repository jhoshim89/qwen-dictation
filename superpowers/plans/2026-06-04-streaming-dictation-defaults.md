# Streaming Dictation Default Parameters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the guessed streaming-timing constants with research-backed defaults, and lock them with a contract test so they don't silently drift.

**Architecture:** The three timing constants live at module scope in `whisper-dictation.py` and are copied verbatim into the build-entry twin `app_main.py`. `Recorder._stream_loop` sleeps `STREAM_INTERVAL` between transcription passes; `_stream_tick` commits a span when `should_commit(window_secs, paused, MAX_WINDOW_SEC)` is true, where `paused` is `trailing_silence(..., PAUSE_SILENCE_SEC)`. No logic changes — only the constant values and a guard test.

**Tech Stack:** Python, pytest, Qwen3-ASR (local). No new dependencies.

---

## Researched Defaults (decision record)

> **Measurement update (applied, then user-tuned):** After the research below, we measured Qwen3-ASR inference on this Mac (mps): **~0.1 s per pass for 1–8 s windows**. That overturns the research's "0.8 s keeps a slow local model from backlogging" assumption — the model is not the bottleneck; the **poll interval** is, because the last words only appear at the next tick. The user then confirmed by feel that the remaining "last word shows up late" was the poll gap, not the silence threshold. Shipped values after the live trials: **`STREAM_INTERVAL = 0.25`, `PAUSE_SILENCE_SEC = 0.3`, `MAX_WINDOW_SEC = 12.0`**. `PAUSE_SILENCE_SEC` bottoms out near 0.3 s (below that, natural 0.1–0.2 s inter-word gaps trigger premature commits and chop sentences); the poll interval was lowered to 0.25 s instead to shave end latency without that risk. The table below records the research baseline.


Source research summarized from real streaming-ASR systems. The dominant lever for "the tail finalizes late" is the **end-of-utterance silence** timeout, NOT the max-window cap (silence almost always commits first; the window cap is a rarely-hit safety net).

| Constant | Old (guessed) | New (sourced) | Why / Source |
|---|---|---|---|
| `PAUSE_SILENCE_SEC` (end-of-utterance silence) | 0.8 → 0.6 | **0.6** | Sits between whisper_streaming's 500 ms and AssemblyAI single-speaker 560 ms; Deepgram's documented "standard" customization is 500 ms. 0.6 s tolerates dictation thinking-pauses while still feeling responsive. Sources: ufal/whisper_streaming `silero_vad_iterator.py` (`min_silence_duration_ms=500`); AssemblyAI universal-streaming turn-detection (560 ms single-speaker); Deepgram endpointing docs. |
| `STREAM_INTERVAL` (re-transcribe cadence) | 0.7 | **0.8** | whisper_streaming's documented baseline `--min-chunk-size` is ~1.0 s; the practical band is 0.5–1.0 s. 0.8 s keeps on-screen updates snappy while leaving a heavy local 1.7B model enough time to finish each pass without backlog. Below ~0.5 s a local model falls behind. Source: ufal/whisper_streaming README. |
| `MAX_WINDOW_SEC` (forced-commit safety net) | 12.0 → 6.0 | **12.0** | Whisper-family models degrade past their ~30 s frame ceiling; a 12 s cap sits well under it and rarely fires because silence commits first. Dropping to 6 s needlessly chops long run-on speech mid-sentence with no latency benefit (the tail latency is governed by `PAUSE_SILENCE_SEC`, not this cap). Source: Whisper 30 s frame design; foges upstream uses 30 s as the whole-recording cap. |

**Net change vs. the currently-running values** (`STREAM_INTERVAL=0.7`, `PAUSE_SILENCE_SEC=0.6`, `MAX_WINDOW_SEC=6.0`): keep `PAUSE_SILENCE_SEC=0.6`, restore `STREAM_INTERVAL` to `0.8`, restore `MAX_WINDOW_SEC` to `12.0`.

**Upstream note:** `foges/whisper-dictation` is a record-then-transcribe batch app with NO streaming/silence/chunk parameters — these constants are entirely this fork's additions, so there is no upstream value to defer to.

---

## File Structure

- `whisper-dictation.py` — module-scope constants `STREAM_INTERVAL`, `PAUSE_SILENCE_SEC`, `MAX_WINDOW_SEC` (the source of truth).
- `app_main.py` — gitignored build-entry copy; must remain byte-identical to `whisper-dictation.py` (PyInstaller entry can't use a hyphenated name).
- `test_streaming.py` — add a contract test asserting the three defaults. Loads the hyphenated module via `importlib.util.spec_from_file_location("wd", "whisper-dictation.py")` (existing `_load()` helper pattern).

---

### Task 1: Lock the researched defaults with a contract test

**Files:**
- Test: `test_streaming.py` (append one test)
- Modify: `whisper-dictation.py:69-75` (the three constants)

- [ ] **Step 1: Write the failing test**

Append to `test_streaming.py`:

```python
def test_streaming_timing_defaults_are_research_backed():
    wd = _load()
    # Sourced in docs/superpowers/plans/2026-06-04-streaming-dictation-defaults.md
    assert wd.STREAM_INTERVAL == 0.8       # re-transcribe cadence (0.5-1.0s band)
    assert wd.PAUSE_SILENCE_SEC == 0.6     # end-of-utterance silence (whisper_streaming 0.5 / AssemblyAI 0.56)
    assert wd.MAX_WINDOW_SEC == 12.0       # forced-commit safety net, well under Whisper's 30s ceiling
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest test_streaming.py::test_streaming_timing_defaults_are_research_backed -v`
Expected: FAIL — current file has `STREAM_INTERVAL == 0.7` and `MAX_WINDOW_SEC == 6.0` (assertion error on `STREAM_INTERVAL`).

- [ ] **Step 3: Set the constants to the sourced values**

In `whisper-dictation.py`, the constant block should read exactly:

```python
STREAM_INTERVAL = 0.8        # 초: 스트리밍 갱신 주기(0.5~1.0초 권장대, 로컬 1.7B가 밀리지 않게)
PAUSE_SILENCE_SEC = 0.6      # 초: 끝이 이만큼 조용하면 쉼 → 확정(말끝 지연을 좌우하는 핵심 손잡이)
# 매 틱마다 '확정 이후의 창 전체'를 다시 받아쓴다. 보통은 쉼(PAUSE_SILENCE_SEC)에서 먼저
# 확정되므로 이 상한은 거의 안 걸린다. Whisper 계열 30초 한계보다 한참 아래로 두는 안전망.
MAX_WINDOW_SEC = 12.0        # 초: 창이 이보다 길면 강제 확정(드물게 걸리는 안전망)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./venv/bin/pytest test_streaming.py::test_streaming_timing_defaults_are_research_backed -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `./venv/bin/pytest -q`
Expected: all tests pass (the `should_commit` tests pass `max_secs` explicitly, so they are unaffected).

---

### Task 2: Sync the build-entry twin and verify compilation

**Files:**
- Overwrite: `app_main.py` (from `whisper-dictation.py`)

- [ ] **Step 1: Copy source of truth onto the build twin**

Run: `cp whisper-dictation.py app_main.py`

- [ ] **Step 2: Verify they are identical**

Run: `diff -q whisper-dictation.py app_main.py`
Expected: no output (files identical).

- [ ] **Step 3: Byte-compile both entry points**

Run: `./venv/bin/python -m py_compile whisper-dictation.py app_main.py`
Expected: no output, exit 0.

---

### Task 3: Manual verification and commit

**Files:** none (verification + commit only)

- [ ] **Step 1: Restart the dev app**

Run: `pkill -f "whisper-dictation.py"; sleep 2; ./run.sh > /tmp/qwen_dev.log 2>&1 &`
Then dictate a long sentence. Expected feel: the tail finalizes within ~0.6 s of stopping; long run-on speech is no longer chopped at 6 s.

- [ ] **Step 2: Confirm no overlay errors**

Run: `grep -c "drawRect error" /tmp/qwen_dev.log`
Expected: `0`.

- [ ] **Step 3: Commit**

```bash
git add whisper-dictation.py test_streaming.py docs/superpowers/plans/2026-06-04-streaming-dictation-defaults.md
git commit -m "tune: research-backed streaming dictation defaults (0.8/0.6/12s)"
```

(Note: `app_main.py` is gitignored and intentionally not committed.)

---

## Self-Review

**Spec coverage:** Three constants selected with sources (Task 1), build twin synced (Task 2), verified + committed (Task 3). Covered.

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code/command step shows exact content. OK.

**Type consistency:** Constant names `STREAM_INTERVAL`, `PAUSE_SILENCE_SEC`, `MAX_WINDOW_SEC` match across the test, the source file, and `should_commit(window_secs, paused, max_secs)`'s `MAX_WINDOW_SEC` argument at the call site. OK.
