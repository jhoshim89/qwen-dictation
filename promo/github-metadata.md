# GitHub Repository Metadata

Use this metadata before posting the repository publicly.

Applied to `jhoshim89/qwen-dictation` on 2026-06-12. Refresh this after GitHub
CLI auth is valid again; the live repository description still used older
hotkey wording when checked on 2026-06-16.

## Description

```text
Local-first macOS dictation powered by Qwen3-ASR. Hold Right Ctrl, speak, and type into any app.
```

## Homepage

```text
https://jhoshim89.github.io/qwen-dictation/
```

## Topics

```text
macos
dictation
speech-to-text
asr
qwen
local-ai
privacy
accessibility
mlx
productivity
```

## `gh` command

Run from the repository root with a GitHub account that can administer the repo:

```bash
gh repo edit jhoshim89/qwen-dictation \
  --description "Local-first macOS dictation powered by Qwen3-ASR. Hold Right Ctrl, speak, and type into any app." \
  --homepage "https://jhoshim89.github.io/qwen-dictation/" \
  --add-topic macos \
  --add-topic dictation \
  --add-topic speech-to-text \
  --add-topic asr \
  --add-topic qwen \
  --add-topic local-ai \
  --add-topic privacy \
  --add-topic accessibility \
  --add-topic mlx \
  --add-topic productivity
```

## Auth note

If `gh auth status` reports an invalid token, run:

```bash
gh auth login -h github.com
```
