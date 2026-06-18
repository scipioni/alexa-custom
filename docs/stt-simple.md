# Triggers

System has:
- wake words
- triggers with commands and actions

Wake words and commands are detected by STT if followed by silence. In this case system emit a "good tone" 

```
wake_words:
  - "ascolta assistente"
  - "ehi galileo"

trigger:
  - commands: ["che ore sono"]
    with_wake: false
    actions: []
  - commands: ["aiuto aiuto"]
    with_wake: false
    actions: []
  - commands: ["dormi"]
    with_wake: true
    actions: [] 
```

STT is capturing speech and match wake words and commands. 
Trigger is activated if STT match one of commands and, if specified, previous detected wake word.

A bad tone is emitted if command of trigger with with_wake=true is not matched by STT.

Normally wake word is detected by silence but system can process commands in one breath mode. System activate trigger if match wake word + command + silence. Therefore, in this case, silence and good tone after wake word is not necessary and a speech like "ascolta assistente che ore sono" activate trigger.

Examples:
"che ore sono" -> emit good tone and run actions
"ascolta assistente che ore sono" -> emit good tone and run actions
"ascolta assistente puoi accendere la luce" -> emit bad tone if "puoi accendere la luce" is not a command


# STT backend — vosk

The design uses **one always-on transcription model** (no cheap-gate stage). The
backend is `vosk` (sherpa-onnx support was removed due to high CPU load, fragmented utterances, and long load times); the two candidates were benchmarked on the real board
(Arduino Uno Q / Snapdragon 801, 4 cores) with `scripts/bench_stt.py`, driving the
production capture path (`parec`) and the free-vocabulary model continuously.

| Metric (live mic, always-on) | vosk | sherpa-onnx (removed) |
|---|---|---|
| Model load time | **2.8 s** | 40 s |
| CPU (continuous decode) | **66–70 %** (~⅔ core) | 103 % (~1 core) |
| RTF p95 (decode/audio) | 0.39–0.75 | 0.31 |
| Endpoint latency p95 | **1059 ms** | 1806 ms |
| Live transcripts | **clean, full** (`ascolta assistente che ore sono`, `aiuto aiuto`) | **fragmented** (`Ai`, `Ascolta`, mid-word cuts) |
| Idle false fires | 0 | 0 |

**Decision: `vosk` is the default and only supported backend; sherpa-onnx support has been removed.**

- sherpa's **40 s load** makes hot-reload (config changes apply in ~4 s) unusable.
- sherpa **fragments utterances** at `vad_silence_ms=500`, chopping mid-phrase
  (its internal endpoint rules don't settle before the software VAD finalizes),
  which breaks command matching.
- vosk loads in seconds, costs ~⅔ core always-on, and produces clean transcripts
  where the **wake word is captured on every utterance** — what matching needs.

Both keep up in real time (RTF p95 < 1) and fit the 4-core budget with headroom
for Piper TTS + LiveKit.

### Tuning notes

- **`vad_silence_ms` ≈ 900 ms.** `500 ms` chops utterances; `900 ms` gives clean
  transcripts. Perceived latency ≈ `vad_silence_ms` + ~130 ms decode, so this knob
  trades cleanliness against snappiness (700–800 ms can be probed if ~1 s feels slow).
- **Open-vocabulary wobble** (e.g. `figure sono` for "che ore sono") is expected
  without a grammar and is absorbed by the fuzzy `matching_threshold`; wake words
  transcribe cleanly regardless.
- The silence-feed benchmark (vosk 98 % / sherpa 195 % CPU) reads faster than
  real time and is a **stress** metric — the rate-limited mic figures above are the
  true always-on cost.

Re-run `scripts/bench_stt.py` after backend or loop changes to catch regressions.


