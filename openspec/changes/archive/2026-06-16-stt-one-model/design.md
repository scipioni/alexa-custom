## Context

`alexa_custom/stt.py` runs a two-stage recognition pipeline: a cheap stage-1 gate (Vosk grammar, Vosk free-vocab, sherpa-onnx, or sherpa-hotwords/KWS) that detects wake words / direct triggers, then a stage-2 model that captures the command. `run_stt_worker` loads both models; `_recognition_loop` (~700 lines) has three parallel firing paths (`is_kws` / `is_vosk` / sherpa-else), and `_single_stage_loop` is a fourth. Triggers are pre-partitioned by `config.py` into `triggers` (global), `direct_triggers` (`wake_words: []`), and per-group `WakeWordGroup.triggers` (scoped). A large knob surface (`partial_matching`, `kws_one_breath`, `partial_stability_*`, `vosk_grammar`, `confidence_mode`, KWS thresholds, `recognition.mode`) exists almost entirely to make the cheap gate behave.

`docs/stt-simple.md` proposes collapsing this to a single always-on transcription model plus a flat `commands[] + with_wake` trigger model.

Hard constraints from the target board (Arduino Uno Q / Snapdragon 801, per CLAUDE.md): PortAudio is unusable — capture via `parec`, playback via `pw-play`; `num_threads` kept low to leave CPU headroom. The two-stage gate existed precisely to avoid decoding open-vocab 24/7, so always-on full transcription is the central performance risk.

## Goals / Non-Goals

**Goals:**
- One STT model, loaded once, backend-configurable (`vosk`, `sherpa-onnx`).
- A single transcribe→match→gate→tone→dispatch loop replacing the four firing paths.
- Flat trigger model: `commands: [...]` + `with_wake: bool`, with a "recently woken" state + timeout.
- Endpoint-driven firing (no partial-match early firing).
- A config migration path (old keys → new) with clear errors/warnings.

**Non-Goals:**
- Changing the action dispatch layer (`actions.py`) or the action types themselves.
- Changing audio capture/playback transport (`parec`/`pw-play`) or AudioWatcher.
- Adding new STT backends beyond what exists (vosk, sherpa-onnx).
- LLM fallback behavior changes (kept as-is, keyed off no-match).

## Decisions

### D0: Default backend = vosk (from on-board benchmark)
On-board results (Arduino Uno Q, 4 cores, `scripts/bench_stt.py`, always-on free-vocab single model):

| backend | model load | always-on CPU (mic) | RTF p95 | live latency p95 | live accuracy |
|---|---|---|---|---|---|
| **vosk** ✅ | 2.8 s | 66–70 % | 0.39–0.75 | **1059 ms** | **clean, full transcripts; wake word always captured** |
| sherpa-onnx | 40 s | 103 % | 0.31 | 1806 ms | fragmented (`'Ai'`, `'Ascolta'`, mid-word cuts) |

Decision: **`stt.backend: vosk` is the default**, sherpa-onnx kept as a configurable option. Rationale: sherpa's 40 s load makes the ~4 s hot-reload feature unusable and it fragments utterances; vosk loads in 2.8 s, costs ~⅔ core always-on, produces clean full transcripts (`'ascolta assistente che ore sono'`, `'aiuto aiuto'`), and has tight ~1 s latency. RTF p95 0.75 sits at the rule-of-thumb threshold but is fine in practice — rate-limited stream, 70 % CPU, no backlog. Open-vocab transcription wobble (`'figure sono'` for "che ore sono") is absorbed by `matching_threshold`; wake words are always clean. *Note*: the silence-feed CPU/RTF figures (vosk 98 %, sherpa 195 %) are an unbounded-rate stress metric; the rate-limited mic run is the true always-on cost.

### D1: One model, free-vocabulary, endpoint-gated
Load a single recognizer from `stt.backend`. Drop grammar mode entirely — grammar only made sense as a cheap gate. Matching runs on the **finalized** transcript (Vosk `Result()`/`FinalResult()` on endpoint, or software-VAD force-finalize after `stt.vad_silence_ms`), then fuzzy-matched against wake words + command phrases.
- *Alternative considered*: keep grammar mode for vosk to cut false positives. Rejected — it reintroduces the dual-path complexity and can't transcribe arbitrary one-breath commands.

### D2: `with_wake` replaces the trigger taxonomy
`Trigger` gains `with_wake: bool` (default `true`) and `commands: list[str]`. `config.py` stops partitioning into `direct_triggers`/scoped/global; `ActionsConfig.triggers` becomes a single flat list. Matching logic:
```
on confirmed transcript T:
    if patterns match (per-trigger, before fuzzy): handle as command match
    if T fuzzy-matches a wake word:        # may also contain trailing command (one-breath)
        emit good tone; open wake window
        strip wake tokens → residual command C
        if C matches a with_wake:true trigger: dispatch
    else:
        for trigger in triggers:
            if trigger.with_wake and not woken(): skip
            if any cmd in trigger.commands (or patterns) matches T:
                emit good tone; dispatch; break
```
- **Scoping dropped — no escape hatch.** Audit of `conf/actions/*.yaml` confirmed only one cross-group scoped trigger (`chiama assistenza` → `help`); making it `with_wake: true` (fires after any wake) is acceptable/preferable for an emergency action. Everything else scoped to `[default]` — the only ordinary wake group — maps cleanly to `with_wake: true`.

### D6: `wake_words` becomes a flat list of phrases — `WakeWordGroup` removed
Per `docs/stt-simple.md`, `wake_words` is a plain list of strings, not group mappings. This **removes `WakeWordGroup`** and everything it carried: `id`, per-group `aliases`, per-group `triggers`, `lang`, `skip_unmatched_inline`. Today's group word + aliases simply become individual flat entries (e.g. `["ehi assistente", "ascolta assistente", "ehi galileo", "ehi sofia", "aiuto", "aiutami"]`). `_build_alias_map`, group-id resolution, and `WakeWordGroup.triggers` merging in `config.py` are deleted.
- *Alternative considered*: keep groups for future scoping. Rejected — without scoping there is nothing for a group to bind, and `id`/`skip_unmatched_inline` exist only to serve the removed two-stage paths.

### D7: `commands`, `aliases`, `patterns`, and `on_reply`
- `phrase: X` + `aliases: [A, B]` → `commands: [X, A, B]`. `phrase` is accepted as legacy sugar for a single-element `commands` (loader warns).
- **`patterns` retained as-is** — an orthogonal word-glob field on triggers, tested before fuzzy matching against the confirmed transcript (unchanged engine).
- **`on_reply` triggers unified to `commands`** — reply-window triggers use the same `commands` shape (yes/no with their alternatives). `with_wake` is meaningless inside a reply window and is ignored there. Reply matching still uses `reply_matching_algorithm`/`reply_matching_threshold`.

### D3: Recently-woken state as a monotonic deadline
A single `wake_deadline: float` (monotonic). Wake match sets `wake_deadline = now + wake_window`. `woken()` is `now < wake_deadline`. A successful `with_wake:true` dispatch may refresh or clear it (follow-up semantics reuse the existing `follow_up` machinery). New config key `recognition.wake_window` (seconds; default ~8s, aligning with today's `command_max_timeout`).

### D4: Backend abstraction stays in `stt_backends.py`
Reuse the existing `STTBackend` interface (`accept_waveform`, `text`, `partial_text`, `reset`, `finalize`). The single loop talks only to this interface, so vosk vs sherpa differences stay hidden. Remove `SherpaKeywordSpotter` and grammar-construction helpers (`_grammar_json*`) once no longer referenced.

### D5: Config schema migration
- `STTConfig`: add `backend`, `model_path`, `num_threads`, `vad_silence_ms`, `rms_threshold`, `adaptive_rms`, `adaptive_rms_margin`, `min_speech_ms`, `wake_match_threshold`. Drop `stage1`/`stage2`.
- `RecognitionConfig`: drop `mode`, `partial_matching`, `kws_one_breath`, `partial_stability_*`, `command_timeout`/`command_max_timeout` (capture window no longer exists). Add `wake_window`.
- `wake_words`: parsed as a flat `list[str]` (see D6); `WakeWordGroup` and `_parse_wake_word_groups` removed.
- `Trigger`: drop `wake_words` partitioning use; add `with_wake: bool` (default true), `commands: list[str]`; retain `patterns`. Keep `phrase` + `aliases` as accepted legacy sugar folded into `commands`.
- Loader emits a `ConfigError` or warning when it encounters removed keys (`recognition.mode`, `stt.stage1/stage2`, `vosk_grammar`, `keyword_spotter`, `wake_words:` group mappings, trigger `wake_words:`), pointing to the new equivalent.

## Risks / Trade-offs

- **Always-on open-vocab CPU/thermal load on Snapdragon 801** → Mitigate: keep `num_threads` low; gate decoding behind the existing RMS/VAD energy check so the model only advances on speech-energy chunks; benchmark vosk-small vs sherpa on-board before committing; keep the energy gate (`rms_threshold`, `adaptive_rms`) as the cheap front filter.
- **More false fires** — open-vocab + fuzzy matching has a wider false-positive surface than grammar-constrained recognition → Mitigate: rely on `matching_threshold` + `min_word_overlap` + `min_cmd_words`; keep `post_dispatch_cooldown_ms`; dump-trigger WAV path retained for tuning.
- **Lost per-wake-word scoping** → Mitigate: confirm `conf/actions/*.yaml` has no scoped trigger in real use; if it does, add the optional escape hatch from D2.
- **Breaking config** for existing deployments → Mitigate: migration notes in proposal + loader warnings; ship a migrated `conf/config.yaml` and `conf/actions/*.yaml`.
- **Latency regression** — finalizing only on endpoint may feel slower than partial-match firing → Mitigate: tune `vad_silence_ms`; one-breath path still fires in a single utterance.

## Migration Plan

1. Land config schema changes with back-compat shims (accept old `phrase`/`wake_words` and warn).
2. Migrate `conf/config.yaml` and `conf/actions/*.yaml` to the new schema in the same change.
3. Implement the single loop behind the new schema; delete the two-stage loops and KWS/grammar code once tests pass.
4. Update/replace affected test suites; ensure `test-stt-e2e` skill passes on-board or in CI.
5. Rollback: revert the branch; the old two-stage config remains in git history.

## Open Questions

- ~~Is per-wake-word scoping actually used?~~ **Resolved**: audit found no meaningful use; scoping dropped, no escape hatch (D2).
- ~~What happens to `patterns`?~~ **Resolved**: retained as-is (D7).
- ~~Do `on_reply` triggers move to the new model?~~ **Resolved**: unified to `commands` (D7).
- ~~`vad_silence_ms` default~~ **Resolved**: `500` chops utterances; `900` gives clean vosk transcripts. Default **`vad_silence_ms: 900`**. Latency ≈ `vad_silence_ms` + ~130 ms decode, so this knob trades cleanliness vs snappiness — 700–800 ms can be probed later if ~1 s feels slow.
- ~~Run the vosk live benchmark~~ **Done**: confirmed (clean transcripts, p95 1059 ms, 70 % CPU). D0 locked.
- `wake_window` default — is reusing the ~8s `command_max_timeout` value right, or should it be shorter (e.g. 4s) to limit accidental gated fires?
- Should `phrase`/`aliases` legacy sugar be retained permanently, or removed after the in-repo configs are migrated?
- On-board benchmark: which single backend (vosk free-vocab vs sherpa-onnx) meets the CPU/latency budget with one always-on model?
