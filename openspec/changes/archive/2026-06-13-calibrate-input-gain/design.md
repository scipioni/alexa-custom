## Context

The system already has `set_input_gain()` / `get_input_gain()` in `audio_hw.py`, a `save_volume_config()` pattern writing to `conf/state.yaml`, and a `get_similarity_score()` function in `actions.py`. The action dispatcher pattern (`@registry.register`) and the `listen_fn` / TTS engine are available as handler kwargs. This change adds one new handler — no new modules, no new dependencies.

Input gain currently lives in `conf/config.yaml` under `audio.input_gain` (user-set) and is shadowed at runtime by `_state.input_gain`. Calibrated gain should persist in `conf/state.yaml` (like volume), loaded at startup and taking precedence over the config file value.

## Goals / Non-Goals

**Goals:**
- Find the optimal input gain via an interactive 5-probe adaptive loop
- Reuse existing `get_similarity_score()`, `set_input_gain()`, TTS, and `listen_fn`
- Persist the calibrated gain to `conf/state.yaml`
- Configurable probe range and calibration sentence via action params

**Non-Goals:**
- Continuous background calibration
- Multi-language calibration prompts
- Calibrating any parameter other than input_gain

## Decisions

### D1 — Adaptive 3+2 probe strategy

**Decision**: Round 1 probes three equidistant gains (low/mid/high) across the configured range. Round 2 probes two values in the half-interval around the Round 1 winner.

**Rationale**: 5 probes total keeps the calibration under ~60s. A pure binary search with 5 steps would only cover a single path; the bracket-then-zoom approach covers the full range first, then refines.

**Alternative considered**: Fixed uniform sweep (5 evenly spaced values). Simpler, but the step size is fixed and doesn't focus on the best region.

**Tie-breaking**: When two gains score equally, prefer the lower value — less amplification means a better noise floor.

### D2 — Gain persistence in state.yaml, not config.yaml

**Decision**: Write calibrated gain to `conf/state.yaml` (alongside `output_volume`), loaded at startup before the audio pipeline starts.

**Rationale**: `conf/config.yaml` is user-editable and round-trips through ruamel.yaml (comment-preserving). Writing a runtime-derived float there would be surprising. `state.yaml` is the established pattern for runtime-calibrated values (`save_volume_config` precedent).

**Implementation**: Add `save_input_gain_config(gain)` and `load_input_gain_state()` to `audio_hw.py` mirroring the volume functions. Update `client.py` startup to load it.

### D3 — 0.5s settle delay after set_input_gain

**Decision**: `await asyncio.sleep(0.5)` after each `set_input_gain()` call before starting TTS+listen.

**Rationale**: OS-level gain change via `pactl` takes effect immediately, but the PipeWire graph may buffer a brief window of audio at the old gain. 0.5s ensures the gain is stable before the user starts speaking. Configurable via `settle_ms` param.

### D4 — Score = get_similarity_score with levenshtein

**Decision**: Reuse `get_similarity_score(transcript, sentence, "levenshtein")` for scoring.

**Rationale**: Already present, handles Italian text with diacritics. Levenshtein is character-level which is appropriate for short fixed sentences. No new dependency.

### D5 — listen_fn unavailable → log warning and return

**Decision**: If `listen_fn` is `None` (e.g. action fired outside the main daemon loop), log a warning and return immediately without probing.

**Rationale**: Same guard already used in `handle_ask`.

## Risks / Trade-offs

- **User fatigue**: 5 repetitions of the same sentence. Mitigated by announcing progress ("prova N di 5") and keeping the sentence short.
- **Background noise during calibration**: A loud environment will inflate scores at all gain levels, producing a valid but non-optimal result. No mitigation — caller's responsibility to run in a quiet environment.
- **Input gain range vs hardware limits**: Gains above 1.0 may clip on some hardware. The default high probe (1.2) is conservative; users can widen via params.
- **state.yaml write failure**: Logged as warning; calibrated gain applied in-process for the session but not persisted. Non-fatal.

## Open Questions

- Should `load_input_gain_state()` at startup override `config.yaml`'s `audio.input_gain`, or only serve as default when no config value is set? (Proposed: state.yaml always wins if present, matching volume behavior.)
