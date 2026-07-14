## Context

This is the low-risk subset of a broader god-file review. Two targets, both grounded by inspection:

- `display.py:117` defines `_FONT5X7 = bytes(...)` spanning ~479 lines (to ~595), referenced only once at `display.py:966` inside `_Ssd1306`. It is allocated at import on every host, including headless ones.
- `audio_hw.py` (901 lines) cleanly partitions at line ~481: runtime state/routing above (`_AudioState`, `configure`, `get_*`/`set_output_volume`/`set_input_gain`, `pulse_session`, `enforce_audio_state`, `check_newpie_ready`, `_restore_hw_pcm`, PipeWire resolution), CLI/diagnostics below (`list_devices`, `speakerphone`, `list_env_devices`, `setup_audio`, `audio_doctor` + helpers `_find_alsa_card`, `_amixer_pcm_percent`, `_usb_ids_for_alsa_card`, `_find_pipewire_source`).

Verified import topology: all console-script entry points route through the `audio.py` facade (`[project.scripts]` → `alexa_custom.audio:*`), and internal runtime importers (`audio_watcher`, `audio_ops`, `tts`, `stt_gating`, `record`, `client`, `web`, `actions`) import only runtime names from `audio_hw`. No internal module imports the CLI functions directly.

## Goals / Non-Goals

**Goals:**
- Stop paying the font allocation on headless/display-disabled startups.
- Separate the daemon's audio hot path from interactive diagnostic tooling so they no longer share a blast radius.
- Zero observable behavior change; zero entry-point/import-path breakage.

**Non-Goals:**
- Touching `stt.py`, `config.py`, or `web.py` (deferred; `stt.py` specifically waits for `stt-liveness-hardening` to land first).
- Re-architecting the audio layer's deeper coupling (`audio_ops` ↔ `audio_hw` global state). Out of scope for quick wins.
- Any change to rendered output, audio behavior, or config.

## Decisions

### 1. Font: dedicated `display_fonts` module, imported lazily by the backend
Move `_FONT5X7` into `alexa_custom/display_fonts.py` and import it *inside* `_Ssd1306` (lazy `from alexa_custom.display_fonts import FONT5X7` at construction or first render), not at `display.py` top level. **Rationale**: keeps the data out of the import path entirely for non-OLED hosts and is trivially testable (assert the symbol isn't bound after a bare `import display`). **Alternative considered**: keep it in `display.py` but wrap in a module-level lazy `@functools.cache` getter — works, but still ships 479 lines in the hot file and is harder to assert "not loaded." Extraction is cleaner.

### 2. Audio: new `audio_diagnostic.py`, re-exported by the `audio.py` facade
Move the CLI/diagnostic functions and their private helpers into `alexa_custom/audio_diagnostic.py`; they import runtime names from `audio_hw` as needed (dependency points diagnostics → runtime, never the reverse). Update `audio.py` to re-export the moved names so `audio:main`, `main_devices`, `main_test`, `setup_audio`, `main_doctor` resolve unchanged. **Rationale**: preserves the public facade contract; the dependency direction matches the natural layering. **Alternative considered**: leave them in `audio_hw` and just add section comments — rejected, doesn't address the shared blast radius and keeps the file at 901 lines.

### 3. Verification by character: tests stay byte-identical
`test_display.py` and `test_audio.py` must pass unchanged. Add one new guard test per the spec: a bare `import` of the display module does not bind/materialize the font.

## Risks / Trade-offs

- **A missed internal importer of a moved CLI function** → grep confirmed none today; the `audio.py` re-export is a safety net even if one is added later. Run the full suite + a manual `alexa-devices` / `alexa-audio-doctor` invocation post-split.
- **Lazy font import adds per-render latency on OLED hosts** → import is cached after first use; OLED rendering already does I2C I/O that dwarfs a one-time module import. Negligible.
- **Circular import between `audio.py` facade and `audio_diagnostic.py`** → avoid by having `audio_diagnostic` import from `audio_hw` (the leaf), never from `audio.py`. The facade imports diagnostics, not vice versa.

## Migration Plan

1. Extract font → `display_fonts.py`; lazy-import in `_Ssd1306`; add headless-import guard test.
2. Create `audio_diagnostic.py`; move CLI funcs + helpers; wire `audio.py` re-exports.
3. Run `task test` + `task lint`; manually invoke `alexa-devices` and `alexa-audio-doctor`.

Rollback: each extraction is an isolated move + re-export; revert either independently.
