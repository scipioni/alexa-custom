## Why

Two oversized modules carry dead weight and mixed concerns that slow navigation and inflate import cost, with no behavioral payoff:

- `display.py` (1264 lines) defines a **479-line `_FONT5X7` bitmap loaded at module import** — paid on *every* startup, including headless / display-disabled deployments that never render a glyph.
- `audio_hw.py` (901 lines) mixes **critical runtime audio state/routing** (volume, gain, PipeWire/ALSA enforcement, PCM-reset workarounds) with **interactive CLI/diagnostic tooling** (`list_devices`, `speakerphone`, `list_env_devices`, `setup_audio`, `audio_doctor`). A change to a diagnostic tool sits in the same blast radius as the daemon's audio hot path.

These are the lowest-risk, highest-readability wins from the broader god-file review. They are purely structural — no behavior changes.

## What Changes

- **Lazy/extracted font**: move `_FONT5X7` out of module scope so it is materialized only when an SSD1306 (`_Ssd1306`) display is actually constructed — either lazily inside the backend or in a dedicated `display_fonts` module imported only by that backend. Headless startups stop paying for it.
- **Split `audio_hw.py` into runtime vs diagnostics**: extract the CLI/diagnostic functions (`list_devices`, `speakerphone`, `list_env_devices`, `setup_audio`, `audio_doctor`, and their private helpers) into a new `audio_diagnostic.py`. Runtime state/routing stays in `audio_hw.py`. The `audio.py` facade re-exports the moved names so all entry points (`alexa-devices`, `alexa-audio*`, `alexa-audio-doctor`, `alexa-audio-setup`) and import paths are unchanged.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `visual-feedback`: add a deferred-font-loading requirement — display font resources SHALL NOT be materialized at module import, only when an OLED backend is instantiated. This is the one observable, testable change. The `audio_hw.py` split is purely internal (no requirement-level behavior change) and needs no spec delta.

## Impact

- **Code**: `alexa_custom/display.py` (font extraction), new `alexa_custom/audio_diagnostic.py`, `alexa_custom/audio_hw.py` (remove CLI funcs), `alexa_custom/audio.py` (re-export moved names).
- **Public API / entry points**: unchanged. `audio.py` remains the facade; `[project.scripts]` targets are untouched.
- **Internal importers**: `audio_watcher`, `audio_ops`, `tts`, `stt_gating`, `record`, `client`, `web`, `actions` import only *runtime* names from `audio_hw` — verified none import the moved CLI functions directly.
- **Tests**: `test_audio.py` and `test_display.py` must stay green unchanged. Add a guard that importing `display` does not materialize the font (assert headless import cost).
- **Backward compatibility**: no breaking changes; no config or behavior changes.
