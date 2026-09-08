# Launch posts (draft, 2026-09-08)

Target: developers who use local LLMs / Mac power users. Goal: GitHub stars.
Post order that usually works: r/LocalLLaMA first (fast feedback), then Show HN on a weekday morning US time, then X and GeekNews.

Repo: https://github.com/jhoshim89/qwen-dictation
Site: https://jhoshim89.github.io/qwen-dictation/
Release: https://github.com/jhoshim89/qwen-dictation/releases/tag/v0.1.0

---

## 1. Hacker News — Show HN

**Title** (80 chars max):
Show HN: Qwen Dictation – local push-to-talk dictation for macOS using Qwen3-ASR

**Text:**

I dictate a lot of Korean/English mixed text with technical vocabulary, and every Whisper-based tool I tried kept mangling the terms or shipping audio off-device. So I forked whisper-dictation and swapped the STT stack for Qwen3-ASR (1.7B), running fully local on Apple silicon.

Hold Right Ctrl, speak, release. Text streams into whatever app has focus — Cursor, Slack, a browser textarea, anything.

What's different from the usual Whisper wrappers:

- Qwen3-ASR handles Korean/English code-switching and specialist vocabulary noticeably better than Whisper in my daily use. No cloud, no API key.
- Live streaming: it retranscribes a rolling audio window every 0.8 s and types only the diff, so you see text appear while you speak instead of after you stop.
- User vocabulary: you register names/terms once and they're fed as context bias at commit time, not as find-and-replace.
- Optional MLX engines (8-bit Qwen3-ASR, Nemotron 3.5 ASR 0.6B) for faster load and first inference.
- Privacy hardening: temp WAVs deleted per pass, diagnostics log contains no transcript text, dashboard APIs bound to localhost with a per-process token.

Honest caveats: install is a terminal one-liner, not a signed .app yet. macOS only. Needs Microphone + Accessibility permissions. It's an MVP built with heavy help from AI coding agents — I review behavior, not every line.

MIT licensed. Would love feedback from people running other local ASR models on Mac.

---

## 2. Reddit — r/LocalLLaMA

**Title:**
I replaced Whisper with Qwen3-ASR in a macOS push-to-talk dictation app — fully local, streams text into any app (MIT)

**Body:**

Repo: https://github.com/jhoshim89/qwen-dictation

Background: I dictate a lot of Korean/English mixed notes full of technical terms. Whisper-based tools kept butchering the vocabulary, so I forked `foges/whisper-dictation` and rebuilt the STT path around **Qwen3-ASR 1.7B**.

How it works:
- Menu-bar app. Hold **Right Ctrl** to dictate, **Right Option** to toggle a session.
- Every 0.8 s it retranscribes the current audio window and types only the visible diff into the focused input, so text appears live.
- Engines selectable from a local dashboard: Qwen3-ASR 1.7B (torch/MPS, default), Qwen3-ASR 1.7B 8-bit via **MLX**, Qwen Original, Nemotron 3.5 ASR 0.6B (MLX).
- Models get a synthetic warm-up after load — first MPS inference used to cost ~10 s, now it's ready before you press the key.
- Vocabulary: register terms once → passed as context bias at commit time (no string replacement dictionary).

Privacy: audio never leaves the machine, temp files removed after each transcription, no transcript text in logs.

Install (Apple silicon, Homebrew):
```
curl -fsSL https://raw.githubusercontent.com/jhoshim89/qwen-dictation/main/install.sh | bash
```

Limitations: terminal install, no notarized .app yet, macOS only.

Things I'd like input on: anyone benchmarked Qwen3-ASR vs Parakeet/Canary on Mac for streaming? And is there interest in a Linux port?

---

## 3. Reddit — r/macapps (shorter)

**Title:**
Qwen Dictation — free, open-source, fully local push-to-talk dictation for Mac (Qwen3-ASR, no cloud)

**Body:**

Hold Right Ctrl, talk, and it types into whatever app is focused. All speech recognition runs on your Mac with Qwen3-ASR — nothing is uploaded. Good with mixed-language and technical vocabulary; you can register your own terms.

Free and MIT licensed. Currently a developer-style install (one terminal command), signed .app is on the roadmap.

https://github.com/jhoshim89/qwen-dictation

---

## 4. X / Threads

Qwen Dictation: local push-to-talk dictation for macOS.

Hold Right Ctrl → speak → text streams into any app.
Qwen3-ASR 1.7B on Apple silicon, zero cloud.
Handles Korean/English mixing and technical vocab far better than Whisper in my daily use.

Free, MIT. Star if useful ⭐
https://github.com/jhoshim89/qwen-dictation

---

## 5. GeekNews (news.hada.io) — 한국어

**제목:**
Qwen Dictation — Qwen3-ASR로 만든 완전 로컬 macOS 받아쓰기 앱 (오픈소스)

**본문:**

한영 혼용에 전문용어가 많은 글을 받아쓰기로 자주 쓰는데, Whisper 계열 도구가 용어를 계속 틀려서 직접 만들었습니다. `foges/whisper-dictation`을 포크해 음성인식 부분을 Qwen3-ASR 1.7B로 교체했습니다.

- 오른쪽 Ctrl을 누른 채 말하면, 지금 포커스된 앱에 글자가 실시간으로 입력됩니다.
- 0.8초마다 다시 인식해서 바뀐 부분만 타이핑하는 방식이라 말하는 도중에 글자가 나타납니다.
- 완전 로컬. 오디오가 밖으로 나가지 않고, 임시 파일은 매 인식 후 삭제, 로그에 전사 텍스트 없음.
- 사용자 단어장: 이름·전문용어를 등록하면 확정 시점에 컨텍스트로 반영됩니다(문자열 치환 아님).
- MLX 엔진(8-bit Qwen3-ASR, Nemotron 3.5 ASR) 선택 가능.

한계: 터미널 한 줄 설치, 서명된 .app은 아직 없음, macOS 전용.

AI 코딩 에이전트 도움을 많이 받아 만든 MVP입니다. 피드백 환영합니다.

https://github.com/jhoshim89/qwen-dictation

---

## Before posting — 3 things that move star count

1. **Demo GIF at top of README.** Biggest single lever. 10–15 s, plain text field, Right Ctrl held, text appearing. See `docs/demo-guide.md`.
2. Pin the repo on the GitHub profile.
3. Reply to every comment in the first 2 hours (HN especially).
