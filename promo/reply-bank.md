# Reply Bank

## Is audio sent to a server?

No. The default flow uses local ASR on your Mac. The installer downloads the
model from Hugging Face, then inference runs locally.

## Does it work in any app?

It types through the normal macOS input path, so it works in ordinary text
fields across apps like editors, browsers, chat apps, and mail. Apps with custom
or restricted input behavior may need testing.

## Why Right Ctrl?

Right Ctrl is easy to hold while speaking and is less likely to conflict with
normal typing shortcuts. Right Option can be used as a toggle.

## How accurate is it?

Accuracy depends on language, microphone, noise, and vocabulary. The project is
currently strongest as a developer-friendly local dictation MVP, not a regulated
transcription system.

## Why Qwen?

The project is experimenting with local ASR engines optimized for this app's
workflow. Qwen3-ASR is the default because it performs well for the current
Korean and vocabulary-aware use case.

## Can I use it without the terminal?

Not yet as a polished consumer install. The current install flow is developer
oriented. A signed app, updater, and model manager are the right next steps for a
paid convenience build.

## Why should I star it?

Star it if you want a local-first Mac dictation app that works directly in the
apps you already type in. Stars help validate whether this should become a more
polished app package.

## What Mac hardware do I need?

The project is currently aimed at Apple Silicon Macs. Exact performance depends
on the model, memory, microphone, and selected ASR engine. Please include your
Mac model when reporting performance.

## Why is the install terminal-based?

The project is still at the developer MVP stage. The install script makes it
possible to test the workflow before investing in a signed app, updater, and
model manager.

## Will there be a normal `.app` installer?

That is the likely next product step if people find the core dictation loop
useful. The packaging work should include signing, notarization, updates, and
model management.

## How is this different from macOS Dictation?

The current focus is a developer-friendly local ASR workflow with a push-to-talk
trigger, configurable hotkeys, local model experiments, and vocabulary handling.
It is not trying to be a polished system replacement yet.

## Can I use another model?

Not through a polished UI yet. More models should be added through a model
manager rather than one-off command-line flags.

## Does it support Windows or Linux?

No. The current app is macOS-specific because it depends on macOS menu-bar,
hotkey, accessibility, and typing behavior.
