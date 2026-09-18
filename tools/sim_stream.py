"""실제 ASR 모델(qwen_mlx)로 스트리밍 틱을 그대로 돌려 화면에 남는 글자를 시뮬레이션한다.

마이크 없이 스트리밍 경로(틱 → 확정 → 타이핑)를 회귀 검증할 때 쓴다. 가짜 키보드가
insert/backspace 를 받아 '화면 글자'를 재구성하고, 전체 파일을 한 번에 받아쓴 결과와 비교한다.

usage: ./venv/bin/python tools/sim_stream.py <whisper-dictation.py 경로> <16kHz mono wav> [틱당 프레임수]

테스트 음성 만들기(한국어 TTS): say -v Yuna -o s1.aiff "문장" → ffmpeg -i s1.aiff -ac 1 -ar 16000 s1.wav
문장 사이에 sox 로 0.7초 무음을 넣어 이어붙이면 쉼 확정 경로까지 지나간다.
출력 swallowed_ticks: 재인식 결과가 달라졌는데 화면에 아무것도 못 넣은 틱 수(0 이어야 정상).
"""
import sys, importlib.util, threading, collections, difflib, json, time
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, soundfile as sf

mod_path, wav_path = sys.argv[1], sys.argv[2]
frames_per_tick = int(sys.argv[3]) if len(sys.argv) > 3 else 6   # 6*64ms ≈ 0.38초/틱

spec = importlib.util.spec_from_file_location("wd", mod_path)
wd = importlib.util.module_from_spec(spec); spec.loader.exec_module(wd)

audio, sr = sf.read(wav_path, dtype="int16")
assert sr == 16000
if audio.ndim > 1: audio = audio[:, 0]
pcm = audio.tobytes()
FRAME = wd.FRAMES_PER_BUFFER * 2
frames = [pcm[i:i+FRAME] for i in range(0, len(pcm), FRAME)]

transcriber = wd.SpeechTranscriber("mps", None, asr_engine="qwen_mlx")
transcriber.min_volume = 12
transcriber.domain_context = ""

class App: min_volume = 12; asr_engine = "qwen_mlx"; domain_context = ""
rec = wd.Recorder.__new__(wd.Recorder)
rec.audio_lock = threading.Lock(); rec.audio_frames = []; rec.window_start = 0
rec.committed_text = ""; rec.last_typed = ""; rec.recording = True
rec.rebaseline_pending = False; rec.self_type_guard_until = 0.0
rec.defer_typing_until_stop = False; rec.append_only_until_stop = False
rec.app = App(); rec.transcriber = transcriber; rec._session_id = 1
rec.session_vocab = []
rec.debug_events = collections.deque(maxlen=5000)
rec._debug = lambda reason, **kw: rec.debug_events.append(dict(reason=reason, **kw))

screen = {"text": ""}
stats = collections.Counter()
def insert(t): screen["text"] += t
def backspace():
    screen["text"] = screen["text"][:-1]; stats["backspaces"] += 1
class KB: pass
def _type(old, new, append_only=False):
    return wd.type_diff(old, new, KB(), allow_empty=True, insert=insert,
                        append_only=append_only, delete_backward=backspace)
rec._type = _type

# 기준: 전체 파일을 한 번에 받아쓴 결과
ref = transcriber.transcribe_file(wav_path, language="ko")
t0 = time.time()
for i in range(0, len(frames), frames_per_tick):
    with rec.audio_lock:
        rec.audio_frames.extend(frames[i:i+frames_per_tick])
    rec._stream_tick("ko")
rec.recording = False
rec._stream_tick("ko", allow_stopped=True)
elapsed = time.time() - t0

typed = [e for e in rec.debug_events if e["reason"] == "typed"]
swallowed = [e for e in typed if e["old_len"] == e["new_len"] and not e.get("rewrite")]
rewrites = [e for e in typed if e.get("rewrite")]
def compact(s): return "".join(s.split())
ratio = difflib.SequenceMatcher(None, compact(screen["text"]), compact(ref)).ratio()
print(json.dumps({
    "module": mod_path.split("/")[-1], "ticks": len(range(0, len(frames), frames_per_tick)),
    "typed_events": len(typed), "swallowed_ticks": len(swallowed), "rewrite_ticks": len(rewrites),
    "backspaces": stats["backspaces"], "screen_chars": len(compact(screen["text"])),
    "ref_chars": len(compact(ref)), "similarity_to_ref": round(ratio, 3), "sec": round(elapsed, 1),
}, ensure_ascii=False))
print("SCREEN:", screen["text"])
print("REF   :", ref)
