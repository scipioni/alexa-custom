## 1. Eval harness scaffolding (no behaviour change)

- [x] 1.1 Add an injectable audio source to the stage-1 loop in `alexa_custom/stt.py` (or extract the per-chunk decision into a reusable helper) so WAV chunks can be fed in place of `parec`, exercising the real decode/confuser/confidence/RMS/KWS paths
- [x] 1.2 Create the harness module (e.g. `alexa_custom/wake_eval.py`) that loads a labelled corpus, feeds each clip through stage-1 at 16 kHz mono s16le in production chunk sizes, and records a wake/no-wake decision per clip with no microphone or PortAudio
- [x] 1.3 Add a console entry point `alexa-wake-eval` (pyproject script) for running the harness and sweeps
- [x] 1.4 Verify the harness runs headless and opens no PortAudio playback/capture stream

## 2. Corpora

- [x] 2.1 Define a labelled corpus layout (positive/ and negative/ directories or a manifest) with provenance metadata per clip
- [x] 2.2 Generate the positive corpus from Piper: "ehi galileo" and "assistente" across available voices, speaking rates, and gain-attenuation levels
- [x] 2.3 Generate Piper-synthesised negatives: non-wake Italian sentences and deliberate near-misses ("Gabriele", "galleria", "assistenza")
- [ ] 2.4 Add a small set of recorded ambient/room/TV and/or Italian Common Voice clips to the negative corpus, with attenuated far-field variants; resolve storage (in-repo vs download step) per design Open Question
- [x] 2.5 Document corpus regeneration in the relevant docs file (docs/wake_word_eval.md)

## 3. Metrics and reporting

- [x] 3.1 Implement false-positives-per-hour (false wakes / total negative-audio duration) and miss-rate (missed positives / total positives) computation
- [x] 3.2 Print per-run report with counts, total negative-audio duration, FP/hour, and miss-rate; ensure deterministic output for a fixed corpus + config
- [x] 3.3 Implement configuration sweep (backend, threshold/confidence, confidence_mode) emitting a one-row-per-config comparison table of FP/hour vs miss-rate
- [x] 3.4 Establish a baseline file and a regression-guard mode (non-zero exit / flagged output when FP/hour or miss-rate exceeds baseline)

## 4. Stage-1 Vosk tuning fixes

- [x] 4.1 Add `stt.stage1.confidence_mode` (`first` | `min` | `mean`) to `alexa_custom/config.py` with default `first`; document in `conf.example/config.yaml`
- [x] 4.2 Replace the `words[0]` confidence read in `stt.py` (~line 1521) with aggregation across all matched-phrase tokens per `confidence_mode`
- [x] 4.3 Add the RMS energy pre-gate to the Vosk stage-1 branch using `_rms_level` and `stt.stage1.rms_threshold`, gating acceptance (not feeding/partials)
- [x] 4.4 Add unit tests for confidence aggregation modes and the RMS pre-gate (synthetic word/conf lists and RMS values)

## 5. Measurement and comparison

- [x] 5.1 Run the harness on the current Vosk config to record the baseline FP/hour and miss-rate
- [x] 5.2 Run the harness after the tuning fixes and record the delta (sweeping confidence_mode and rms_threshold)
- [ ] 5.3 Run the sweep including the sherpa-onnx KeywordSpotter stage-1 backend on the identical corpora; produce the Vosk-vs-KWS comparison table
- [x] 5.4 Summarise findings and a recommended `confidence_mode`/threshold (and whether to pursue a KWS backend switch as a follow-up) in the change docs

## 6. Validation

- [x] 6.1 Run `task lint` and `task test`; ensure no regressions
- [ ] 6.2 Verify live stage-1 behaviour is unchanged on the target board with default config (`confidence_mode: first`), confirming the refactor did not alter production detection
- [x] 6.3 Record the chosen baseline for the regression guard
