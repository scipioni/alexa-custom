# Proposal: harden-serena-runtime

## Why

A full audit of the path from `task audio:setup` through daemon runtime (2026-07-09) found that the `one-model` branch has drifted out of compliance with its own specs — MQTT/HA integration, config hot-reload, graceful shutdown, and the systemd watchdog all exist as code with no callers or no enabling configuration — and that runtime resilience is asymmetric: the STT thread is supervised while the LiveKit worker (the daemon's core purpose) can die silently with errors reported only to dashboard WebSocket clients, never to the journal. Several concrete bugs also break the project's own documented diagnostic workflows (trigger-dump WAVs, SP92-direct gst-launch pipeline).

## What Changes

### Restore spec compliance (drifted features)
- Wire MQTT back into `main()`: construct `MQTTClient` from config, pass it through `_async_main` and `start_stt_thread`, register the reload callback (`make_mqtt_reload_callback` currently has zero callers).
- Wire config hot-reload into the production path: start `ConfigManager`'s watcher in the default daemon run (not only under `--hot-reload`), make web-UI saves trigger reload, and preserve `secrets` overrides (`llm_host`/`llm_api_key`) across reloads.
- Handle SIGTERM in the web/daemon path so `systemctl stop`/`restart` runs the existing ordered teardown (LiveKit disconnect, thread stop, display clear) instead of only SIGINT.
- Make the systemd watchdog actually deployable: ping during the idle trigger-wait loop and during LiveKit sessions; keep the STT heartbeat fresh (or exempted) during legitimate long dispatches (`dispatch_timeout` = 90 s) so enabling `WatchdogSec` doesn't kill healthy conversations.

### Supervise the LiveKit worker
- Add an exception handler + supervised restart loop around the LiveKit worker (parity with the STT watchdog), and log worker errors to the journal via `logger.error` — not only to the dashboard WebSocket queue.
- Fix the STT restart loop: exponential backoff on deterministic crashes (model reload is expensive on this board) and pass the chained `_on_stt_event` callback so the display keeps receiving STT events after a restart.

### STT capture recovery and correctness
- Recover a stalled-but-alive capture process in-process: after a bounded no-data window, kill and restart the capture subprocess instead of looping on a DEBUG log forever.
- Catch all exceptions (not only `RuntimeError`) around STT model load; retry with backoff instead of ending the thread.
- Re-evaluate hot-reloaded config and re-resolve the capture device periodically (or on reload signal), not only when the capture process dies.
- Fix the gst-launch pipeline builder: restore the missing `audioconvert` between `audiocheblimit` and `webrtcdsp` (breaks the documented SP92-direct config at link time); deduplicate the two pipeline builders so they cannot drift again.
- Fix trigger-dump WAVs: buffer holds post-downmix mono, so size the byte budget for 1 channel and write 1-channel WAVs (currently 16 s buffers written as 2-channel, corrupting `task stt:analyze-dumps`).
- Apply the confidence gate to the `finalize()` tail in reply capture.
- Resolve the adaptive-RMS clamp contradiction (code caps the threshold down; comment says the opposite — decide which is intended and align).

### Subprocess and playback hardening
- Add timeouts to `amixer` (`_restore_hw_pcm`) and `pactl` (`set_input_gain`) subprocess calls; add SIGKILL escalation to `_run_capture_tool`'s capture branch and STT capture teardown.
- Log playback failures: remove `except Exception: pass` + `stderr=DEVNULL` from `play_wav_file`; unify error handling across `_play_array`/`_play_raw`/`play_wav_file`.
- Re-resolve the cached output sink after device replug (hook into `AudioWatcher` reconnect) so `pw-play --target` never points at a vanished node.

### Cleanup (drift removal)
- Delete dead code: `_graceful_shutdown` orphan wiring (or re-wire it — see SIGTERM item), `set_stt_gated_flag`, `get_pipewire_device` cache + its invalidation call, `subscribed_tracks`, unused `pulse`/constructor params, duplicate imports/device queries in `client.py`.
- Delete `setup/99-switch-on-connect.conf` (ships the module documented as crashing PipeWire 1.4.2 on this board; `task audio:setup` already deletes installed copies).
- Merge `_play_array`/`_play_raw` (~95 % duplicated).

Non-goals: no behaviour change to wake-word matching (`task eval` corpus stays green), no new features, no changes to the audio:setup shell scripts beyond deleting the stale conf file.

## Capabilities

### New Capabilities
- `livekit-worker-supervision`: supervised restart + journal logging for the LiveKit worker loop; watchdog pings sent in idle/session states.
- `stt-capture-recovery`: in-process recovery of a stalled-but-alive capture subprocess; model-load retry with backoff; periodic config/device re-resolution in the recognition loop.

### Modified Capabilities
- `graceful-shutdown`: add requirement — SIGTERM triggers the same ordered teardown as internal restart paths (`systemctl stop`/`restart` is clean).
- `stt-thread-watchdog`: modify heartbeat requirements — heartbeat stays fresh (or dispatch is exempted) during legitimate long dispatches; restart loop uses backoff; restarted thread keeps the chained event callback.
- `yaml-config`: add requirement — hot-reload watcher runs in the default production daemon (not only `--hot-reload`); reload preserves secrets overrides.
- `audio-management`: add requirements — output sink re-resolved after device replug; playback failures are logged (never silently swallowed); subprocess calls in the enforcement path have timeouts.

Unchanged-spec restorations (implementation drift, no delta needed): `mqtt-integration` already requires connect-at-startup — this change restores compliance.

## Impact

- **Code**: `alexa_custom/client.py` (main wiring, worker supervision, watchdog pings, SIGTERM), `web.py` (STT restart loop, hot-reload gating, signal handling), `config_manager.py` (secrets on reload, watcher start), `stt.py` / `stt_gating.py` / `stt_capture.py` / `stt_gst_capture.py` (recovery, dump fix, builder dedup, finalize gate), `audio_hw.py` / `audio_ops.py` / `audio_watcher.py` (timeouts, sink re-resolution, playback logging, dedup), `setup/99-switch-on-connect.conf` (delete), possibly `setup/serena.service` (WatchdogSec once pings are correct).
- **Behaviour**: MQTT/HA discovery starts publishing again on boards with `mqtt:` configured (was silently off — verify HA side effects on deployed boards). Config edits on the board take effect without restart. `systemctl restart` becomes clean.
- **Risk**: watchdog enablement is the riskiest item — gate it behind correct ping coverage and test long LLM conversations under `WatchdogSec`; MQTT re-enable may surface stale HA entities.
- **Tests**: targeted pytest per module; `task eval` must stay 100/100; `test-stt-pipeline` skill for recognition-loop wiring; on-board validation for SP92-direct gst-launch config and trigger dumps.
