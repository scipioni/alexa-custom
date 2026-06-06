## Context

`alexa-client` runs as a headless systemd user service. Dozens of constants governing audio timing, STT sensitivity, device identity, and reconnect behaviour are either hardcoded literals or only reachable via environment variables — making tuning a code-edit/restart cycle. Three separate `os.execv()` call sites (config hot-reload, source watcher, web dashboard restart) kill all threads without cleanup. On a headless device, config parse errors are invisible. The MQTT queue grows without bound when the broker is unreachable.

## Goals / Non-Goals

**Goals:**
- All tuneable knobs reachable from `config.yaml` with safe defaults matching current hardcoded values (no behaviour change on upgrade)
- Single graceful shutdown path shared by all three `os.execv()` call sites
- Audible feedback on config parse failure (TTS "errore di configurazione" + log)
- Piper voice validated at `init_engine()`, not at first `say()`
- MQTT outgoing queue capped (configurable, default 200 messages)

**Non-Goals:**
- Streaming TTS / phonetic matching (separate changes)
- MQTT TLS or authentication
- Web dashboard authentication
- `shell` action sandboxing

## Decisions

### 1 — Config schema extension: flat optional fields with defaults

New fields added to `ActionsConfig` as `Optional` with defaults matching current hardcoded values. Config format stays backward-compatible — existing `config.yaml` files require no changes.

```yaml
# New fields (all optional, defaults shown)
audio_card_name: NewPie          # was hardcoded in audio.py
audio_sample_rates:
  usb: 48000                     # was _SAMPLERATE dict
  bluetooth: 16000
  internal: 48000
audio_post_playback_ms: 100      # was AUDIO_POST_PLAYBACK_MS env var
audio_tone_preroll_ms: 300       # was AUDIO_TONE_PREROLL_MS env var
audio_mic_gain: 300              # was hardcoded pactl 300%
stt_chunk_size: 4096             # was _CHUNK literal
stt_vad_silence_ms: 700          # was STT_VAD_SILENCE_MS env var
stt_stage1_vad_silence_ms: 500   # was STT_STAGE1_VAD_SILENCE_MS env var
stt_stage1_rms_threshold: 0.02   # was STT_STAGE1_RMS_THRESHOLD env var
reconnect_delay: 5               # was _RECONNECT_DELAY literal
mqtt_queue_max: 200              # new; no prior bound
```

Env-var overrides (e.g. `AUDIO_POST_PLAYBACK_MS`) remain honoured for backward-compatibility, checked after config value, so they can still override per-deploy.

### 2 — Graceful shutdown: centralised async function in client.py

Extract a single `async def _graceful_shutdown(config_manager, livekit_manager, mqtt_client, stt_stop_event)` called by all three restart sites. Sequence:

```
1. stt_stop_event.set()           # signal STT thread to stop
2. await mqtt_client.publish_offline()  # LWT + disconnect
3. await livekit_manager.leave()  # graceful LiveKit leave
4. await asyncio.sleep(0.3)       # let tasks drain
5. os.execv(...)                  # restart
```

`config_manager` and `web.py` receive a `shutdown_callback: Callable[[], Coroutine]` at construction that they call instead of invoking `os.execv()` directly. This avoids circular imports: the callback is a closure created in `_async_main`.

### 3 — Config error feedback: callback in ConfigManager

`ConfigManager` gains an `on_config_error: Callable[[str], None] | None` slot. When a reload raises `ConfigError`, the manager calls this callback with the error message then retains the previous config. In `_async_main`, the callback is wired to a small helper that calls `tts.get_engine().say("Errore di configurazione")` in a thread (non-blocking, best-effort).

No new machinery — uses the existing TTS engine that is already initialised before the watcher starts.

### 4 — Piper voice validation at init

`init_engine()` currently catches import errors but not missing voice files. Add a check:
- Verify `voice_path.exists()` before loading
- Attempt to instantiate `PiperVoice.load(voice_path)` inside `init_engine()`
- On failure, log the error and fall back to Pico (existing fallback path), rather than raising

This keeps the same fallback semantics but surfaces the problem at startup rather than deferring it.

### 5 — Bounded MQTT queue

Replace `asyncio.Queue()` with `asyncio.Queue(maxsize=mqtt_queue_max)`. In `publish()`, use `put_nowait()` wrapped in a try/except `QueueFull`; on overflow, drain one item (the oldest) with `get_nowait()` and log a warning before retrying `put_nowait()`.

### 6 — Passing config into audio/stt modules

`audio.py` and `stt.py` currently read module-level globals set at import time. The cleanest path without a full refactor:

- `audio.py`: add `configure(cfg: ActionsConfig)` function called from `_async_main` after config loads and after each hot-reload. Updates module-level `_POST_PLAYBACK_MS`, `_TONE_PREROLL_MS`, `_SAMPLERATE`, and the default card name.
- `stt.py`: pass thresholds explicitly to `_recognition_loop()` and `capture_transcript()` via parameters sourced from config. Module-level env-var globals remain as fallback defaults.

This avoids threading issues (values set before the STT thread reads them) and keeps the change surface small.

## Risks / Trade-offs

- **Graceful shutdown adds ~300 ms to restart time** → acceptable; restarts are rare and user-initiated
- **Config error TTS fires on a headless device with no active STT** → TTS plays through the speaker; if audio is down, error is only in logs. Acceptable: logs are the fallback channel.
- **Env-var overrides layered on top of config** → precedence is config < env var. Documents existing behaviour; env vars win, matching current expectation.
- **Module-level `configure()` in audio.py is not thread-safe for mid-session hot-reload** → values are simple integers/strings; torn reads on reload are benign (worst case: one audio event uses old preroll value)

## Migration Plan

1. All new config fields are optional with defaults → no migration required for existing `config.yaml` files
2. Update `config.yaml.example` with all new fields, documented
3. Env-var overrides still work → no change for existing deployments using env vars

## Open Questions

- Should `stt_chunk_size` be exposed to users? It's a low-level PCM framing detail; exposing it risks misconfiguration. Could omit from `config.yaml.example` but keep in code.
