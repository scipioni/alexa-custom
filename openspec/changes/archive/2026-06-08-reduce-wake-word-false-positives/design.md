## Context

Stage-1 wake detection runs Vosk in restricted-grammar mode (`stt.stage1.backend=vosk`) with wake words "ehi galileo" and "assistente". False positives are confirmed from both other people's conversation and the two-word phrase "ehi galileo" itself.

Code review (`alexa_custom/stt.py`) found three causes:
1. **Single-token confidence** (`stt.py:1521`): `conf = words[0].get("conf")` — only the first token is gated, so "galileo" (the discriminative token) is never confidence-checked.
2. **No RMS gate on the Vosk branch**: `stt.stage1.rms_threshold` only wires into the sherpa open-vocab path; quiet far-field speech reaches the grammar decoder unchecked.
3. **Architectural ceiling**: grammar-Vosk has no reject/garbage path — every speech segment is forced onto the nearest allowed phrase, and grammar confidence is a relative score, not an absolute "was this the wake word".

Critically, there is **no false-positive measurement**. The `test-stt-e2e` skill only synthesises the wake word (true-positive/miss). The KeywordSpotter stage-1 path (already implemented, `wake-word`-style reject path) has never been evaluated for false positives. Tuning without measurement is guessing.

Constraints (CLAUDE.md): the board has no native PipeWire PortAudio backend; `sd.play()`/PyAudio block forever. Any harness must run offline by feeding audio buffers directly into the recogniser, never through a capture/playback device.

## Goals / Non-Goals

**Goals:**
- Make stage-1 false positives and misses **measurable and repeatable** offline, with no microphone.
- Close the two cheap code holes on the Vosk path (all-token confidence, RMS pre-gate) and *measure* their effect.
- Produce a like-for-like data comparison of Vosk vs sherpa-onnx KeywordSpotter on identical corpora.
- Leave a permanent regression guard.

**Non-Goals:**
- Switching the default stage-1 backend to KWS (this change produces the evidence; the switch, if any, is a follow-up).
- Adding a new neural wake-word engine (openWakeWord) or training a custom "galileo" model.
- Changing the stage-1 → stage-2 dispatch contract, audio cues, or MQTT states.
- A second-pass verification layer (kept in reserve).

## Decisions

### D1: Drive the real stage-1 loop with a synthetic audio source, not a parallel reimplementation
The harness MUST exercise the same matching/gating code paths as production, or it measures the wrong thing. Approach: refactor the stage-1 capture so the byte source is injectable — the production path reads from `parec`; the harness feeds 16 kHz mono s16le chunks read from WAV files in the same chunk size. The decision logic (grammar decode, confuser rejection, confidence gate, RMS gate, KWS accept) is reused verbatim.
- *Alternative considered*: reimplement a thin scorer that loads a Vosk/KWS recogniser directly and calls `AcceptWaveform`. Simpler but risks drifting from production behaviour (e.g. reset semantics, cooldown, normalization). Rejected unless the refactor proves too invasive — in which case the scorer MUST import and call the same helper functions (`normalize_text`, `_build_alias_map`, confidence aggregation, `_rms_level`).

### D2: Metric definition — FP/hour and miss-rate
False-positives-per-hour = (false wakes on negative corpus) / (total negative audio duration in hours). Miss-rate = (positive clips that did not wake) / (total positive clips). FP/hour is duration-normalised so corpora of different sizes are comparable and the number maps to lived experience ("≈N false wakes per hour of room conversation"). Miss-rate is per-clip because each positive clip is one intended wake.

### D3: Confidence aggregation is configurable (`stt.stage1.confidence_mode`)
Add `confidence_mode ∈ {first, min, mean}` to `stt.stage1`. `first` reproduces today's behaviour (regression-safe default for single-token words). `min` is the strict choice (every token must clear the bar — best against partial matches). `mean` is a middle ground. Making it a config field lets the harness sweep it as a variable rather than hard-coding a guess.
- *Rationale*: "ehi galileo" mis-fires precisely because "galileo" is unchecked; `min` directly targets that. But `min` may raise misses on noisy true wakes — which is exactly what the harness will quantify before we commit a default.

### D4: Corpus sourcing — synthesise positives with Piper, assemble negatives from mixed sources
Positives: Piper TTS (already a dependency) renders "ehi galileo" / "assistente" across available voices, a few speaking rates, and gain-attenuation levels to emulate distance. Deterministic and reproducible. Negatives: combine (a) Piper-synthesised non-wake Italian sentences and deliberate near-misses ("Gabriele", "galleria", "assistenza"), and (b) optionally a small set of recorded ambient/room/TV clips and Italian Common Voice snippets checked in as fixtures. Attenuated copies emulate far-field cross-talk.
- *Trade-off*: TTS negatives are clean and may understate real-world FPs (real cross-talk is messier). Mitigation: include at least some recorded ambient/Common Voice clips so the negative corpus has natural speech, and label corpus provenance in the report.

### D5: RMS pre-gate placed before grammar acceptance
Reuse `_rms_level(data)` and compare against `stt.stage1.rms_threshold` in the Vosk branch before accepting a wake match (mirroring the sherpa path's energy logic). Below threshold → reset/skip without dispatch.
- *Note*: gate the **acceptance**, not the feeding — partials/UI can still show, but a sub-threshold segment cannot wake.

### D6: Delivery — CLI entry point plus test skill
Expose the harness as a console entry point (e.g. `alexa-wake-eval`) for sweeps and as a repeatable check usable like the existing `test-stt-e2e` skill, so it doubles as the regression guard (D2 metrics vs a recorded baseline).

## Risks / Trade-offs

- **TTS-only corpus understates real FPs** → include recorded ambient + Common Voice clips in negatives; report corpus provenance; treat FP/hour as comparative, not absolute, until validated against a real room recording.
- **Refactor to inject the audio source touches the hot stage-1 loop** → keep the change minimal (source abstraction only); cover with the harness itself and existing `task test`; verify live behaviour unchanged on the board before archiving.
- **`min` confidence mode raises misses** → that is precisely what the harness measures; do not commit a default until the tradeoff curve is seen; keep `first` as the safe default.
- **KWS Italian accuracy uncertain** (BPE tokenisation of "galileo") → the comparison is the deliverable, not a backend switch; a poor KWS curve is a valid, informative outcome.
- **RMS threshold too aggressive drops quiet true wakes** → sweep `rms_threshold` alongside confidence; choose from the curve.

## Migration Plan

1. Land the harness + corpora first (no behaviour change) → establish baseline FP/hour and miss-rate for current Vosk config.
2. Add `confidence_mode` (default `first`) and the RMS pre-gate → re-run harness, record the delta.
3. Run the sweep including KWS → produce the comparison table.
4. Choose a recommended `confidence_mode` / threshold from data; record baseline for the regression guard. Backend switch (if any) is a separate follow-up change.

Rollback: the new config keys default to prior behaviour; reverting the stage-1 edits restores `words[0]` gating with no RMS pre-gate. The harness is additive and can be removed independently.

## Open Questions

- Where do recorded ambient/Common Voice fixtures live and how large can they be without bloating the repo (Git LFS vs. a download step in `alexa-setup`)?
- Should the regression guard fail CI hard, or only warn, given corpus volatility?
- Is the stage-1 loop refactor (D1, injectable source) acceptable, or do we accept a helper-importing scorer (D1 alternative) to avoid touching the hot path?
