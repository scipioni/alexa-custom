# Design: harden-serena-runtime

## Context

An audit of the `task audio:setup` → runtime path (2026-07-09) found the `one-model` branch out of compliance with four existing specs (`mqtt-integration`, `yaml-config` hot-reload, `graceful-shutdown`, `stt-thread-watchdog`), an unsupervised LiveKit worker whose failures never reach the journal, no in-process recovery for a stalled-alive capture subprocess, and a handful of concrete bugs (gst-launch pipeline link failure on SP92-direct, trigger-dump WAV channel math, ungated `finalize()` tail, missing subprocess timeouts, silently swallowed playback errors).

Constraints:
- Target is a resource-constrained aarch64 board; Vosk model load is expensive (seconds), so restart loops must back off.
- The systemd unit currently has no `WatchdogSec`; enabling it is only safe once ping coverage is complete.
- `task eval` (100 % precision/recall) and the byte-budget trigger-buffer rule are hard regression gates.
- All the board-specific audio constraints in CLAUDE.md (pulsectl→`_restore_hw_pcm`, pw-play temp-WAV, no PortAudio I/O) remain in force.

## Goals / Non-Goals

**Goals:**
- Every documented/spec'd runtime behaviour actually runs in the shipped `serena.service` deployment (MQTT, config hot-reload, SIGTERM teardown, watchdog).
- No single-subsystem failure is silent: LiveKit worker errors reach the journal; stalled capture recovers in-process; playback failures are logged.
- Fix the four concrete STT/audio bugs without changing wake-matching behaviour.
- Remove dead code and the dangerous stale `setup/99-switch-on-connect.conf`.

**Non-Goals:**
- No changes to wake-word matching semantics or the eval corpus.
- No changes to `usb-audio-restore.sh` / audio:setup shell logic (only the stale conf file is deleted).
- No new features; no web-UI changes beyond what reload wiring requires.
- Enabling `WatchDogSec` in the shipped unit is prepared but shipped commented-out (opt-in after on-board soak).

## Decisions

### D1 — MQTT: restore, don't remove
`mqtt-integration` and `home-assistant-integration` specs require it and `mqtt:` config plumbing already exists. `main()` constructs `MQTTClient` when `config.mqtt.host` is set, passes it into `_async_main` and `start_stt_thread`, and registers `make_mqtt_reload_callback` with the ConfigManager. Alternative (delete MQTT + archive specs) rejected: HA integration is a stated product feature.

### D2 — Split `--hot-reload` into two concerns
The current flag conflates dev-time `.py` auto-restart with production YAML hot-reload. Decision: the ConfigManager YAML watcher **always runs** in the daemon (spec `yaml-config` requires it); the `.py` source watcher stays behind `--hot-reload`. Web-UI saves call `_reload` unconditionally. `_reload` gains the `secrets` argument captured at startup so reloads preserve `llm_host`/`llm_api_key`. Alternative (keep flag-gated, fix docs) rejected: web-UI config panel and voice-calibration writes depend on reload working in production.

### D3 — LiveKit worker supervision mirrors the STT watchdog
Wrap the worker loop body in `try/except Exception`: log with `logger.exception` (journal), emit the dashboard event as today, then restart the loop after a backoff (5 s doubling to 60 s, reset after 10 min healthy). Missing-env (`require_env`) failures are terminal-with-message: retrying cannot fix them, so log CRITICAL once and keep the daemon alive (web/STT still useful) with a clear journal line. Alternative (let the exception kill the process and rely on systemd `Restart=on-failure`) rejected: an env/config error would restart-loop the whole daemon including expensive model load.

### D4 — Watchdog ping coverage via a single main-loop stamp point
Move `sd_notify("WATCHDOG=1")` into a small helper invoked from every await point of the outer loop: idle trigger-wait loop, participant polling, and in-session wait. STT heartbeat freshness gating stays, but the heartbeat is additionally stamped by `_dispatch_trigger` around dispatch awaits (a "busy but alive" stamp), so a legitimate 90 s dispatch never starves it. A wedged dispatch still starves the heartbeat once the stamp stops advancing (the dispatch loop itself stalls). `setup/serena.service` gains commented `Type=notify` + `WatchdogSec=90` lines with instructions; enabling is a deploy-time decision after soak. Alternative (exempt dispatch from freshness) rejected: it would blind the watchdog to real dispatch hangs.

### D5 — Stalled-capture recovery threshold
In `_iter_gated_audio`, track a monotonic `last_data` timestamp. After `capture_stall_secs` (new config, default 30 s) with the process alive but no bytes, log ERROR, return from the iterator exactly like process-exit — `run_stt_worker`'s existing restart path kills/respawns capture and re-resolves the source. 30 s is far above the SP92 digital-zero gating (which still delivers zero-filled frames, not *no* frames) so quiet rooms don't trigger it. Alternative (SIGKILL the process from inside the iterator) rejected: reuse the one restart path that already exists.

### D6 — Model-load resilience
Wrap `get_stt_backend()` in `except Exception` (not just `RuntimeError`), retry with backoff (10 s → 60 s cap) inside the worker instead of returning. Web `_stt_watchdog_loop` gains the same backoff and passes the chained `_on_stt_event` callback (bug fix). Rationale: a transient FS/OOM error should not leave the daemon permanently deaf; a permanent one now logs on every retry instead of dying silently.

### D7 — In-loop config/device refresh
`_recognition_loop` checks a generation counter (bumped by ConfigManager reload callbacks and by `AudioWatcher` on device reconnect) at chunk-iteration granularity; when it changes, the loop returns so the outer worker loop re-reads config and re-resolves the capture source. This makes hot-reload effective within one chunk (~≤2 s) without tearing down capture on unrelated reloads — only wake/trigger/threshold data is re-read in place where safe; source/profile changes trigger the capture restart. (The existing `gst_profile_change_event` mechanism is generalized rather than duplicated.)

### D8 — Single GStreamer stage builder
Extract the shared stage-construction (`webrtcdsp`, compressor, expander, `audiocheblimit` incl. its surrounding `audioconvert`s) into one function returning a list of element strings; both `_build_pipeline_string` and `_build_gst_launch_cmdline` consume it. This fixes the missing `audioconvert` before `webrtcdsp` in the gst-launch path and makes future drift impossible.

### D9 — Trigger-dump math fixed at the buffer, not the writer
The rolling buffer stores post-downmix mono; set `_audio_buf_max = dump_secs * 16000 * 2` (1 channel) and write 1-channel WAVs. Alternative (buffer pre-downmix stereo) rejected: doubles memory and the analysis tooling expects the audio the recognizer actually saw.

### D10 — Adaptive-RMS: align code to comment (profile is a floor)
Change the clamp to `max(_adaptive, profile_threshold)` semantics — the profile `rms_threshold` is the *minimum* threshold (sensitivity ceiling); the adaptive mechanism may raise the threshold in loud rooms but never drop below the calibrated profile value. Comment and code then agree. Validate on-board with `serena-stt --play` replays before merging; if recall degrades, fall back to fixing the comment only and file a follow-up.

### D11 — Subprocess hardening pattern
Every `subprocess.run` in the enforcement/gain path (`amixer` in `_restore_hw_pcm`, `pactl` in `set_input_gain`) gets `timeout=5` with a caught `TimeoutExpired` → WARNING log. `_run_capture_tool` capture branch and STT capture teardown get SIGTERM → 2 s → SIGKILL escalation (same as the existing non-capture branch). `play_wav_file` logs returncode + stderr on failure (same policy as `_play_array`); `_play_raw` delegates to `_play_array` via `np.frombuffer(...).reshape(-1, ch)`, removing the duplication.

### D12 — Output-sink re-resolution
`AudioWatcher._check_and_enforce` on device (re)connect calls a new `invalidate_output_sink()`; `resolve_output_sink` re-resolves lazily on next playback when invalidated. Lazy (vs eager re-resolve in the watcher) avoids opening extra pulsectl sessions (each one costs a PCM reset/restore round-trip).

## Risks / Trade-offs

- [MQTT re-enable surprises deployed boards: stale HA entities, unexpected discovery publishes] → MQTT only activates when `mqtt.host` is configured (existing spec behaviour); release note calls it out; verify on one board before fleet update.
- [Always-on YAML watcher adds a periodic poll + reload path in production] → 2 s stat-poll is negligible; reload failures already fail-closed (previous config kept).
- [Watchdog enablement kills healthy daemons if ping coverage still has a gap] → ship `WatchdogSec` commented out; soak on one board with journal monitoring for `Watchdog timeout` before enabling anywhere else.
- [Stalled-capture restart could flap on a device that legitimately delivers nothing for >30 s] → capture backends deliver zero-filled frames during silence, not zero bytes; if flapping is observed, raise `capture_stall_secs` — it's config, not code.
- [D10 changes runtime sensitivity behaviour] → gated by on-board replay validation; `task eval` (text-level) unaffected; revert path is a one-line clamp change.
- [Backoff on STT restart delays recovery from a one-off crash] → first retry stays fast (5–10 s); only repeated failures back off.
- [Touching client.py wiring risks the working call path] → keep the worker-loop body unchanged; supervision wraps it. `test-stt-pipeline` + a manual on-board call test before release.

## Migration Plan

1. Land code changes; full `task fix` + `task eval` green.
2. On-board: deploy to the dev board, run `task audio:doctor`, verify MQTT discovery appears in HA (if broker configured), edit `conf/config.yaml` live and confirm reload in journal, `systemctl --user restart serena` and confirm clean teardown lines.
3. Soak ≥24 h with `WatchdogSec=90` enabled manually on the dev board only; check journal for watchdog kills during long LLM conversations.
4. Rollback: single revert commit; no persistent state format changes.

## Open Questions

- Should `mqtt-integration`'s "Offline state on graceful shutdown" also fire on SIGTERM (new path)? Assumed yes — it reuses the same teardown sequence.
- Is `home-assistant-integration` spec still accurate after the `one-model` refactor, or does it need its own audit pass? (Out of scope here; flagged for later.)
