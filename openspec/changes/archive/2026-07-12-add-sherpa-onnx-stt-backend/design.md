## Context

`alexa_custom/stt_backends.py` defines a single `STTBackend` ABC (`accept_waveform(data: bytes) -> bool`, `text()`, `partial_text()`, `reset()`, `finalize()`) with one implementation, `VoskSTT`. `get_stt_backend(cfg, ...)` currently ignores `cfg.backend` entirely and always constructs a `VoskSTT` — there is no branching on backend value yet, despite `STTConfig.backend` and the `single-model-stt` spec already documenting it as a config point.

The recognition loop (`stt.py`, `_recognition_loop`) already implements a backend-agnostic, RMS-energy-based endpoint system used for every backend: it tracks `speech_ms`/`_silence_ms` from a simple RMS threshold (`stt.rms_threshold`, adaptive via `stt.adaptive_rms`), and fires `vad_fire` once accumulated silence exceeds `stt.vad_silence_ms` (900 ms default) or, for partials that already match a wake/trigger phrase, `stt.fast_vad_ms` (400 ms). `backend.accept_waveform(data)` is called on **every** chunk regardless of RMS (Vosk already runs continuously — "single always-on model" per the existing spec). The loop calls `backend.finalize()` on `vad_fire`, or `backend.text()` when the backend's own `accept_waveform()` return value signals an endpoint first.

This session's standalone evaluation (`alexa_custom/asr_eval.py`, see `docs/asr-plan.md`) built and validated a working VAD-gated sherpa-onnx + Kroko Zipformer + Silero VAD pipeline, but as a **bypass** of this architecture: it reads raw capture-process bytes directly, does its own downmix/gain, and owns its own VAD/endpoint/right-context state machine end-to-end. Porting it into `stt_backends.py` is not a lift-and-shift — several of its behaviors are already handled upstream by the existing pipeline, and reusing the existing RMS-based endpoint loop instead of introducing a second, competing endpoint mechanism is both simpler and consistent with `single-model-stt`'s explicit "no mode selector" requirement.

## Goals / Non-Goals

**Goals:**
- Add `sherpa-onnx` as a second `STTBackend` implementation, selectable via `stt.backend`, implementing the exact same ABC Vosk already implements — no changes to `stt.py`'s recognition loop.
- Preserve the two correctness fixes from evaluation that are still relevant in this architecture (VAD onset debounce, Zipformer right-context padding on finalize).
- Provision the backend's model files (Kroko Zipformer + Silero VAD) via `serena-setup`.
- Zero behavior change for `stt.backend: vosk` (default).

**Non-Goals:**
- Not replacing Vosk or changing its default status.
- Not re-solving the quiet-trailing-syllable limitation documented in `docs/asr-plan.md` — expose the same tuning knobs `asr_eval.py` has, but don't promise a fix.
- Not building a second, VAD-driven endpoint system parallel to the existing RMS-based one — see Decisions below for why.
- Not changing `serena-vad`/`asr_eval.py` — it stays as an independent diagnostic tool.

## Decisions

### Reuse the existing RMS-based endpoint loop; Silero VAD becomes an internal CPU-saving gate only

`asr_eval.py` used Silero VAD as *both* (a) the gate deciding whether to feed audio to the (expensive) Zipformer encoder at all, and (b) the endpoint signal deciding when to finalize. In the production backend, only (a) carries over. Endpoint timing stays owned entirely by `stt.py`'s existing `vad_fire`/`fast_vad_ms` mechanism — the same one Vosk already uses.

Rationale: `single-model-stt`'s "Single recognition loop" requirement explicitly rules out per-backend mode branching. Introducing a second, Silero-driven endpoint concept alongside the existing RMS one would violate that, and would need its own tuning (`vad_silence_ms` for RMS vs. a hypothetical Silero equivalent) without a clear benefit — the RMS system is already tuned and battle-tested across the real hardware profiles (NewPie/BT51/SP92) documented in this project's CLAUDE.md.

`SherpaOnnxSTT.accept_waveform(data)`:
1. Converts `data` (already mono, already gain-applied by `stt_gating` upstream — see next decision) to float32 samples.
2. Feeds samples to an internal Silero VAD instance; if `is_speech_detected()` is true, feeds the same samples to the Kroko `OnlineStream` and drains via `is_ready()`/`decode_stream()`. If false, samples are skipped (not fed to the encoder) — this is the CPU-saving optimization the whole `docs/asr-plan.md` proposal is built around, since the Kroko encoder (~150 MB) is far more expensive per-chunk than Vosk's small model.
3. Maintains the same short pre-roll ring buffer `asr_eval.py` used, so the first phoneme isn't lost when Silero flips from silence to speech (this is still needed even though endpoint timing moved outside the backend — it's about not losing the *onset*, not about when to stop).
4. Returns `False` always — this backend does not claim its own endpoint; `stt.py`'s `vad_fire` is authoritative, matching how the loop already treats a backend that offers no faster-than-RMS endpoint signal.

Alternative considered: enable sherpa-onnx's own rule-based endpoint detection (`enable_endpoint_detection=True`, `is_endpoint(stream)`) and return that from `accept_waveform()`, mirroring Vosk's native-decoder-endpoint semantics exactly. Rejected for v1 — no evidence it beats the already-tuned RMS system, and it would need its own `rule1/2/3_min_trailing_silence` config surface. Left as a possible follow-up, not blocking this change.

### No downmix/gain reimplementation in the backend

`asr_eval.py` needed its own `_downmix_to_mono` + `_apply_input_gain` calls because it bypassed the normal capture path entirely (reading raw subprocess bytes). In production, `alexa_custom.stt_gating._iter_gated_audio` already downmixes and gain-applies *before* `data` ever reaches `backend.accept_waveform(data)` — identically for every backend. The stereo-downmix bug found during evaluation is therefore **not applicable** to the production backend; it was an artifact of `asr_eval.py`'s standalone bypass, already fixed at the shared pipeline layer. `SherpaOnnxSTT` only needs to convert already-mono `int16` bytes to normalized `float32`.

### Right-context (tail-padding) on `finalize()`, not on every endpoint

The Zipformer encoder needs ~0.66 s of trailing context to decode an utterance's last word(s) — established in evaluation via sherpa-onnx's own `online-decode-files.py` reference pattern. Because `stt.py` already keeps calling `accept_waveform()` on every subsequent chunk for up to `vad_silence_ms` (900 ms) or `fast_vad_ms` (400 ms) *before* it ever calls `finalize()`, real trailing audio already reaches the backend through ordinary calls in most cases — no backend-side "read ahead from the capture stream" trick (which `asr_eval.py` needed, since *its own* VAD hangover was only 400 ms) is required here.

`SherpaOnnxSTT.finalize()`:
1. Tracks how much trailing near-silence has already been fed via ordinary `accept_waveform()` calls since Silero last saw speech.
2. Pads the shortfall (if any — relevant mainly on the fast 400 ms endpoint path, which is shorter than the 660 ms requirement) with zeros, matching sherpa-onnx's own documented pattern (real audio was already fed by the loop; only the remainder needs synthetic padding).
3. Calls `stream.input_finished()`, drains via `is_ready()`/`decode_stream()`, returns `get_result(stream)`.
4. Matches `VoskSTT.finalize()`'s existing contract exactly: "flush the decoder, return the final text" — `stt.py` doesn't need to know the two backends flush differently internally.

`reset()` recreates a fresh `OnlineStream` (mirroring `VoskSTT.reset()`'s `Reset()` call).

### Config: new `sherpa_`-prefixed fields, reuse `model_path`

`STTConfig` already has generic `model_path`, `num_threads`, `vad_silence_ms`, `min_speech_ms` fields — but the last two are the *outer RMS loop's* concepts (shared across all backends) and must not be conflated with Silero VAD's *internal* onset/hangover debounce, which evaluation showed needs different defaults (100 ms onset debounce vs. Vosk's irrelevant concept; ~400 ms internal Silero hangover as a CPU-gate hysteresis, independent of the outer 900 ms `vad_silence_ms`). New fields, namespaced to avoid ambiguity:

- `model_path` (existing field, reused): for `stt.backend: sherpa-onnx`, points at a Kroko model directory (default `models/it/kroko_64l`) instead of a Vosk directory. Same field, different meaning per backend — consistent with how `num_threads` already works.
- `sherpa_vad_threshold: float = 0.5` — Silero speech-probability threshold.
- `sherpa_vad_min_speech_ms: int = 100` — onset debounce (default lower than sherpa-onnx's own 250 ms default; evaluation showed the default misses short commands).
- `sherpa_vad_min_silence_ms: int = 400` — internal Silero hangover before the CPU-gate closes (independent of the outer `vad_silence_ms`, which decides when `stt.py` calls `finalize()`).
- `apply_input_gain` is **not** a new field — gain is already applied uniformly upstream for every backend (see decision above); the `--apply-config-gain` flag existed in `asr_eval.py` only because that tool bypassed the normal capture path.

### Dependency: optional extra, not a hard dependency

`sherpa-onnx==1.13.3` (1.13.4's aarch64 wheel is broken — verified this session) stays behind an optional install path so `stt.backend: vosk` deployments don't pull in ~150 MB+ of onnxruntime they'll never use. `get_stt_backend()` raises a clear `RuntimeError` at backend-construction time if `stt.backend: sherpa-onnx` is selected but the package isn't importable, naming the install command — mirroring the existing `_load_model()` "Run 'serena-setup' to download it" pattern for missing Vosk models.

Open question (see below): whether to fold the existing `asr-eval` optional-dependency group into this backend's requirement, or keep them separate, since `asr_eval.py`/`serena-vad` remains a standalone tool that shouldn't need to change.

## Risks / Trade-offs

- **[Risk]** Feeding the Zipformer encoder only during Silero-detected speech (skipping chunks during silence) could, in principle, leave the `OnlineStream`'s internal state slightly different from a continuously-fed stream, if sherpa-onnx's streaming decode assumes gap-free input. → **Mitigation**: this is exactly what `asr_eval.py` already validated end-to-end this session (transcription was correct for every non-edge-case phrase tested); the risk is theoretical, not observed.
- **[Risk]** Reusing the RMS-based endpoint instead of a VAD-based one for finalize timing means this backend inherits any RMS-tuning issues that affect Vosk too (e.g. quiet trailing speech under a fixed RMS threshold) — the same "quiet trailing syllable" limitation from evaluation could show up for a different reason at the outer-loop level, not just inside this backend's own Silero gate. → **Mitigation**: document in `docs/asr-plan.md`/CLAUDE.md as a shared limitation, not something to fix here.
- **[Risk]** `models/` is gitignored — the Kroko model files present on this dev board did not arrive through any documented process this session. → **Mitigation**: see Open Questions; the download URL/source must be confirmed before implementation, not assumed.
- **[Trade-off]** Not using sherpa-onnx's own rule-based endpoint detection means this backend can't ever finalize *faster* than the RMS system's `fast_vad_ms`/`vad_silence_ms`, even though the underlying model could in principle support tighter endpoint rules. Accepted for v1 simplicity; can revisit if the RMS backstop proves too slow for this backend specifically.

## Migration Plan

1. Add `sherpa-onnx` model + `silero_vad.onnx` download support to `serena-setup` (opt-in flag, not run by default — mirrors `--piper-voice` being explicit).
2. Add `SherpaOnnxSTT` to `stt_backends.py` and wire `get_stt_backend()` to branch on `cfg.backend`.
3. Add new `STTConfig` fields with defaults matching current Vosk-only behavior when `backend: vosk` (i.e., fields are inert unless `backend: sherpa-onnx`).
4. Manual validation on real hardware (reusing the same test phrases from this session's `docs/asr-plan.md` evaluation) before considering this backend "supported" rather than "experimental."
5. No rollback concerns — `stt.backend: vosk` remains the default and this is purely additive to config/code surface.

## Open Questions

- **Kroko model download source**: `models/it/kroko_64l`/`kroko_128l` are present on this dev board but `models/` is gitignored and no download step currently exists anywhere in this repo. The original `docs/asr-plan.md` names the model `sherpa-onnx-streaming-zipformer-it-kroko-2025-08-06` and references `https://huggingface.co/Banafo/Kroko-ASR`, but no working download URL has been verified this session (unlike `silero_vad.onnx`, whose GitHub-release URL was confirmed working). **Must confirm the exact download source/URL before implementing the `serena-setup` step.**
- Whether `sherpa-onnx` should be its own optional-dependency extra (e.g. `sherpa-onnx`) distinct from the existing `asr-eval` extra used by `serena-vad`, or whether the two should share one extra now that both need the same pinned package version.
- Whether to eventually expose sherpa-onnx's own rule-based endpoint detection as an alternative to the RMS backstop (see Trade-offs) — out of scope for this change.
