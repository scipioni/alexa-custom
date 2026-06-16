## Why

The recognition path has grown into two multiplied axes — an STT *engine* axis (`two-stage`/`single-stage` × `vosk-grammar`/`vosk-free`/`sherpa-onnx`/`sherpa-hotwords`) and a *trigger taxonomy* axis (`global`/`direct`/`scoped`) — held together by a ~700-line `_recognition_loop` with three parallel `is_kws`/`is_vosk`/`else` branches and a thick layer of knobs (`partial_matching`, `kws_one_breath`, `partial_stability_*`, `vosk_grammar`, `confidence_mode`, `skip_unmatched_inline`, …) that exist mainly to make the cheap-gate stage behave. The two-stage design was a CPU workaround: a cheap grammar/KWS gate so the board wasn't decoding open-vocab 24/7. That complexity is now the dominant maintenance and tuning cost. `docs/stt-simple.md` describes a single always-on transcription model that collapses both axes.

## What Changes

- **BREAKING** Replace the two-stage (stage1 cheap-gate + stage2 capture) recognition pipeline with a **single always-on STT model** that continuously transcribes audio. The backend remains configurable (`vosk`, `sherpa-onnx`, …) but there is exactly **one** model loaded, not two.
- **BREAKING** Flatten the trigger taxonomy. Replace `global` / `direct` / `scoped` (encoded as `wake_words: None | [] | [ids]`) with a per-trigger **`with_wake: bool`**:
  - `with_wake: false` — command fires on its own (today's *direct*).
  - `with_wake: true` (default) — command fires only when a wake word was **recently** detected (today's *global*).
- **BREAKING** `wake_words` becomes a flat list of phrase strings; **`WakeWordGroup` is removed** (no `id`, per-group `aliases`/`triggers`, `lang`, or `skip_unmatched_inline`). Per-wake-word scoping is dropped (audit confirmed it is not meaningfully used).
- Replace per-trigger `phrase` + `aliases` with a `commands: [...]` list (legacy `phrase`/`aliases` folded in with a warning). **`patterns` is retained** as an orthogonal word-glob field. `on_reply` triggers are unified to the `commands` shape.
- Detection model: the single model transcribes speech; the system matches the transcript against the configured **wake words** and **command** phrases. A match is acted on when it is followed by silence (endpoint), at which point a **"good tone"** is emitted.
- A `with_wake: true` command fires only if a wake word was detected within a recent window (a new "recently woken" state with a timeout); a `with_wake: false` command fires regardless of wake state.
- Remove the now-obsolete engine/gate knobs (`recognition.mode`, `stage1`/`stage2` split, `vosk_grammar`, `kws_one_breath`, `partial_matching`, `partial_stability_*`, `confidence_mode`, `keyword_spotter`/`hotwords`). Keep fuzzy matching (`matching_algorithm`, `matching_threshold`, `min_word_overlap`) and VAD/endpoint/cooldown controls.
- Collapse `_recognition_loop` + `_single_stage_loop` + the KWS/vosk/sherpa branches into one transcribe→match→(gate on wake)→tone→dispatch loop.
- **UI**: redesign the dashboard trigger canvas (`ww-graph-canvas`) for the flat model. Instead of per-wake-group node trees, the canvas shows exactly **two nodes**: (1) a **wake-words node** listing all wake phrases, and (2) a single **rectangular triggers node** laying out all triggers in a **grid**. Triggers that fire **without** a wake word (`with_wake: false`) are **highlighted** to distinguish them from wake-gated ones. Runtime match-flash highlighting (`_graphFlashByPhrase`) is preserved.

## Capabilities

### New Capabilities
- `single-model-stt`: One always-on, backend-configurable transcription model that emits transcripts + endpoint events; replaces the two-stage gate architecture.
- `command-wake-gating`: The `with_wake` boolean trigger model and the "recently woken" state/timeout that gates `with_wake: true` commands.

### Modified Capabilities
- `multi-stage-stt`: Two-stage pipeline removed/superseded by the single-model loop.
- `trigger-wake-words`: `global`/`direct`/`scoped` taxonomy replaced by `with_wake`; per-wake-word scoping behavior changes.
- `streaming-intent-detection`: Partial-matching / one-breath / partial-stability intent firing removed; firing now keyed on endpoint + match.
- `sherpa-kws-wake-detection`: Dedicated KWS cheap-gate stage removed; sherpa becomes a full-transcription backend choice for the single model.
- `web-interface`: Trigger canvas redesigned to a two-node layout (wake-words node + rectangular grid of triggers) with `with_wake: false` triggers highlighted.

## Impact

- Code: `alexa_custom/stt.py` (loop collapse), `alexa_custom/config.py` (`RecognitionConfig`, `STTConfig`/`STTStage1Config`/`STTStage2Config`, `Trigger.wake_words` → `with_wake`), `alexa_custom/stt_backends.py`, `alexa_custom/stt_phonetics.py` (trigger resolution), `alexa_custom/web.py` (config panel fields + the trigger graph data payload), `alexa_custom/static/dashboard.js` (`_buildGraphData`/canvas render → two-node grid layout), `alexa_custom/dashboard.html`, `conf/config.yaml`, `conf/actions/*.yaml`.
- Config (BREAKING): existing `wake_words: None|[]|[ids]` trigger fields and `recognition.mode`/`stt.stage1`/`stt.stage2`/grammar knobs must be migrated. Need a migration note and/or shim.
- Tests: wake-detection, streaming-intent, multi-stage, sherpa-kws test suites change or are removed; the `test-stt-e2e` skill path must still pass.
- Resolved: per-wake-word scoping is dropped — audit of `conf/actions/` found only `chiama assistenza` → `help`, which becomes `with_wake: true` (acceptable for an emergency action). No escape hatch.
