## Context

The device is a living-room speakerphone running a headless Python process. It currently auto-connects to a LiveKit room at startup and stays connected indefinitely. There is no hands-free interaction — all control is manual or via the TUI.

Vosk and PyAudio are already declared as dependencies (added in a prior setup commit) and the Italian model is downloaded via `alexa-setup`. The audio stack is PipeWire-backed; livekit-ffi runs in a dedicated thread (per project memory — sharing Textual's event loop causes SIGSEGV in the Rust FFI layer).

## Goals / Non-Goals

**Goals:**
- Always-on wake word detection that runs independently of the LiveKit connection state
- Low-CPU Stage 1 (grammar mode) → high-accuracy Stage 2 (full transcription) pipeline
- Config-driven actions triggered by recognized phrases (Telegram send, LiveKit join)
- Audio feedback on wake, recognition, timeout
- No change to existing `alexa-client` behavior when `actions.yaml` is absent

**Non-Goals:**
- Inbound Telegram command handling (future)
- Custom wake word model training
- Multi-room LiveKit orchestration
- Speaker identification / per-user triggers

## Decisions

### D1 — Audio capture via `parec` subprocess, not `AudioStream` tap

**Decision**: Capture microphone audio for Vosk using a `parec` subprocess at 16 kHz, not by tapping livekit's `AudioStream`.

**Rationale**: LiveKit connects on demand — when idle there is no `LocalAudioTrack` to tap. `parec` runs in its own OS process with no ctypes callbacks in Python, avoiding the SIGSEGV risk documented in project memory. It also captures directly at 16 kHz (Vosk's required sample rate), eliminating resampling.

**Alternative considered**: Tap `AudioStream(LocalAudioTrack)` as the VU meters do. Rejected because (a) no track exists when idle, (b) Vosk processing in a ctypes-heavy environment risks the same FFI collision that prompted the `parec` approach for VU meters.

```python
proc = subprocess.Popen(
    ["parec", "--rate=16000", "--channels=1", "--format=s16le",
     "--latency-msec=100"],
    stdout=subprocess.PIPE,
)
```

### D2 — Two-stage recognition: grammar mode → full transcription

**Decision**: Stage 1 uses `KaldiRecognizer` with a grammar word list (just the wake words + `[unk]`). On wake word detection, Stage 2 opens a new `KaldiRecognizer` with no grammar for full transcription within a 3-second window.

**Rationale**: Full transcription on a living-room mic is CPU-intensive and introduces latency. Grammar mode restricts the decoder search space to a handful of words — order-of-magnitude faster, better accuracy for the known set. Stage 2 only runs for a short burst, so full-transcription cost is acceptable.

**Timeout**: 3 seconds (configurable via `actions.yaml: command_timeout`). After timeout, play a "not understood" beep and return to Stage 1.

### D3 — Fuzzy phrase matching with `difflib.SequenceMatcher`

**Decision**: Match Stage 2 transcription against configured trigger phrases using `difflib.SequenceMatcher` with a default threshold of 0.70.

**Rationale**: Italian phonetic variation and living-room acoustic conditions mean exact string match fails too often. `difflib` is stdlib — no extra dependency. Threshold 0.70 catches common inflections (`"chiama"` / `"chiamare"`) without triggering on unrelated phrases.

**Alternative considered**: Word-set overlap (all trigger words present in transcript). Rejected — more fragile with insertions.

### D4 — STT runs in a dedicated daemon thread

**Decision**: `stt.py` runs in its own `threading.Thread` with a plain `while` loop (no asyncio). It communicates results to the action dispatcher via a `queue.Queue`.

**Rationale**: Vosk `AcceptWaveform` is synchronous and blocking. The livekit worker already occupies one asyncio event loop in its own thread. Adding Vosk to either the main thread or the livekit thread would block audio processing. A dedicated thread with a queue decouples recognition latency from action dispatch.

### D5 — LiveKit: connect on demand, not at startup

**Decision**: Extract `_connect_once()` from `_async_main` so it can be called as an action. When `actions.yaml` is present, the process starts without connecting to LiveKit; a `livekit_join` action triggers connection.

**Rationale**: Matches the stated use case (4a from exploration). Keeps the device idle/quiet until voice-triggered.

**Backward compatibility**: When `actions.yaml` is absent, `alexa-client` starts and auto-connects as before.

### D6 — Telegram via direct `httpx` call, no library

**Decision**: Send Telegram messages using a single `httpx.post` to `api.telegram.org`. No `python-telegram-bot` or `telebot` dependency.

**Rationale**: Send-only requires one endpoint (`sendMessage`). A full Telegram library adds significant overhead for one HTTP call. `httpx` is already a likely transitive dependency and is needed for async HTTP elsewhere. The `TelegramClient` class provides a clean abstraction boundary for future inbound polling.

```python
class TelegramClient:
    async def send_message(self, chat_id: str, text: str) -> None: ...
    # Future: async def start_polling(self, handler) -> None: ...
```

## Risks / Trade-offs

- **[Wake word false positives]** "galileo" / "aiuto" are real Italian words that could appear in background speech (TV, radio). → Mitigation: Stage 1 grammar mode requires a clean isolated detection; consider adding `wake_word_confidence_threshold` config option later.
- **[parec device selection]** `parec` without `--device` uses PipeWire default source. If `INPUT_DEVICE` env var names a non-default device, `parec` must be told explicitly. → Mitigation: resolve PipeWire source name from `INPUT_DEVICE` at startup using `pactl list sources short`.
- **[Vosk model accuracy at distance]** The Italian small model (downloaded by `alexa-setup`) is optimized for close-mic. Living-room distance degrades accuracy. → Mitigation: two-stage design mitigates by reserving full transcription for the command window only; users can switch to a larger model by pointing `VOSK_MODEL_PATH` at it.
- **[Thread lifecycle]** The STT thread and livekit thread must both terminate cleanly on Ctrl-C / SIGTERM. → Mitigation: a shared `threading.Event` stop signal is passed to both workers; `parec` subprocess is `.terminate()`d on stop.

## Migration Plan

- Existing users: no change — `actions.yaml` absence keeps current auto-connect behavior
- New users: copy `actions.yaml.example`, fill in Telegram credentials and trigger phrases, restart
- Rollback: delete `actions.yaml` to revert to original behavior without code changes
