## Why

A standalone evaluation this session (`alexa_custom/asr_eval.py`, the `serena-vad` diagnostic tool — see `docs/asr-plan.md` "Validazione Sperimentale su Hardware Reale") validated that sherpa-onnx + the Kroko Zipformer Italian model + Silero VAD produces accurate, low-latency streaming Italian transcription on this board's hardware, fixing three non-obvious bugs along the way (stereo downmix, VAD onset debounce, Zipformer right-context handling). That tool is diagnostic-only: it hardcodes its model path, has no config integration, and requires manually-run model downloads. This change productionizes it as a second, selectable STT backend so it can be run continuously by the daemon and compared against Vosk in real deployments, without disturbing the existing default.

**Important context discovered during implementation, not before proposing this**: a sherpa-onnx backend was already built and shipped in this project previously (hotwords/BPE biasing, a NeMo FastConformer experiment, cross-compilation tooling) and was **deliberately removed** (commits `657f57c`, `b5a2412`) after a documented benchmark (`docs/stt-simple.md`) showed it losing to Vosk on load time (40s vs 2.8s), CPU (103% vs 66-70%), endpoint latency, and transcript fragmentation. The prior implementation did not use VAD-gating (confirmed by inspecting its last version in git history) — this change's Silero VAD CPU-gate is a genuine architectural difference that might improve on the CPU/fragmentation numbers, but the 40s load time is unaffected by VAD-gating and was independently reproduced this session (42-49s) on the same model. This change is treated as a *second attempt*, not a green-field addition: it must be validated against `scripts/bench_stt.py` (the same tool that produced the historical numbers, currently broken — see Impact) before being considered viable, and it must not reintroduce the "any config change stalls the daemon for 40s" risk (see the new "Backend reload cost" requirement in the modified spec).

## What Changes

- Add `sherpa-onnx` as a second valid value for `stt.backend` (currently only `vosk`), implementing the same transcript/endpoint interface the single recognition loop already expects.
- Port the validated VAD-gated streaming logic from `asr_eval.py` into a production backend module: Silero VAD gating with pre-roll ring buffer, real-audio right-context feed before finalizing (not synthetic zero-padding), and the corrected stereo downmix — reusing `alexa_custom.stt_gating` helpers rather than duplicating them.
- Add new `stt` config fields for the sherpa-onnx backend: model variant (`kroko_64l` / `kroko_128l`), `num_threads`, VAD threshold, VAD min-silence-ms, VAD min-speech-ms. Reuse the existing `stt.capture_backend` (parec/gstreamer) mechanism — no parallel capture-selection knob.
- Add Kroko model and `silero_vad.onnx` download support to `serena-setup` (`alexa_custom/setup.py`), matching its existing Vosk model provisioning pattern.
- Document the new backend option in `docs/stt-simple.md` and/or `CLAUDE.md`'s Configuration section.
- `serena-vad` (the standalone tool) is unaffected and remains available for ad-hoc evaluation/benchmarking.
- Vosk remains the default backend; its behavior is unchanged.

## Capabilities

### New Capabilities

(none — this extends the existing single-model-stt capability's already-generic "configurable backend" design rather than introducing new observable system behavior)

### Modified Capabilities

- `single-model-stt`: the "Configurable transcription backend" requirement currently only documents `vosk` as an accepted `stt.backend` value. This adds `sherpa-onnx` as a second accepted value, adds backend-specific tuning options under `stt`, adds a model-provisioning requirement so `serena-setup` fetches the files a configured backend needs, and adds a backend-reload-cost requirement addressing the prior removal's 40s-load-time concern.

## Impact

- **Code**: new backend module under `alexa_custom/` (e.g. `alexa_custom/stt_sherpa_onnx.py` or similar, exact naming decided in design), `alexa_custom/stt_backends.py` (backend selection), `alexa_custom/config.py` (`STTConfig` additions), `alexa_custom/setup.py` (model provisioning).
- **Config**: `conf/config.yaml` and `conf.example/config.yaml` gain new `stt.*` fields (backward-compatible — omitted fields fall back to defaults, existing `vosk`-configured deployments unaffected).
- **Dependencies**: `sherpa-onnx==1.13.3` becomes a real (not just optional-eval) dependency when this backend is selected — needs to move from the `asr-eval` optional extra into a properly gated dependency (design.md to decide: always installed vs. optional extra required for this backend).
- **Models**: `models/it/kroko_64l` (and optionally `kroko_128l`) plus `models/vad/silero_vad.onnx` become provisioned artifacts via `serena-setup`, alongside existing Vosk models.
- **No impact** on existing Vosk-backend deployments — default behavior, config, and dependencies for `stt.backend: vosk` are unchanged.
- **`scripts/bench_stt.py`**: the historical benchmark tool is currently broken (imports the removed `STTStage2Config`) — needs a small fix (use `STTConfig`, re-add `sherpa-onnx` to its `--backend` choices) so it can produce a real, apples-to-apples before/after comparison against the documented historical numbers, as the actual go/no-go gate for this change (not just "manually said a few phrases and it worked").
