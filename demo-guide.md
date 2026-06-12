# Demo Recording Guide

When demo media is added later, it should prove the core promise:

> Hold Right Cmd, speak, and Qwen Dictation types into the app you are already using.

## Target output

- Length: 10-15 seconds.
- Format: GIF for README, MP4 for X/Threads.
- Frame: one focused text field plus a small visible HUD/menu-bar cue.
- No private data, no notifications, no unrelated windows.

## Recommended scene

Use Cursor, ChatGPT, TextEdit, or a browser text area. The best launch demo is a
plain text field because it makes the typing behavior obvious.

Suggested spoken line:

```text
Qwen Dictation is a local Mac dictation app. Hold Right Command, speak, and it types into any app.
```

Korean variant:

```text
오른쪽 커맨드를 누르고 말하면 지금 열려 있는 앱에 바로 입력됩니다.
```

## Recording steps

1. Quit notification-heavy apps or enable Do Not Disturb.
2. Open a blank text field in Cursor, ChatGPT, TextEdit, or a browser.
3. Launch Qwen Dictation.
4. Start screen recording.
5. Hold Right Cmd.
6. Speak the chosen line once.
7. Release Right Cmd.
8. Stop recording immediately after the final text appears.

## Crop and export

- Crop to the active text field and any visible Qwen Dictation HUD.
- Keep the cursor and typed text readable.
- Export:
  - `docs/demo.mp4` for social posts.
  - `docs/demo.gif` for README if the file stays reasonably small.

If the GIF is too large, upload the MP4 to a GitHub issue/comment and use the
GitHub user-attachment URL in the README instead of committing a large binary.

## Acceptance checklist

- The viewer can understand the product without audio.
- The video shows text appearing in the focused app.
- The demo does not show private prompts, contacts, emails, or file paths.
- The first 2 seconds show the starting state.
- The final frame shows the completed dictated text.
