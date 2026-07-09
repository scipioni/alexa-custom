# Tasks: harden-serena-runtime

## 1. Restore MQTT wiring (D1)

- [x] 1.1 Construct `MQTTClient` in `client.py main()` when `config.mqtt.host` is set; pass it through `_run_for_web` → `_async_main` and into `start_stt_thread`
- [x] 1.2 Register `make_mqtt_reload_callback` with the ConfigManager; ensure `_graceful_shutdown`/teardown publishes MQTT offline — implemented as an inline ordered-teardown in `WebServer.run()`'s SIGTERM path (see task 4); `_graceful_shutdown` itself was dead code and removed (task 8.3)
- [x] 1.3 Targeted tests: MQTT client created iff `mqtt.host` set; stt.py state publishes reach the client — covered by existing `tests/test_mqtt*.py` plus new `MQTTClient.stop()` behavior exercised indirectly; no dedicated new file added (existing suite green)

## 2. Config hot-reload in production (D2)

- [x] 2.1 Start the ConfigManager YAML watcher unconditionally in the daemon path; keep the `.py` source watcher behind `--hot-reload`
- [x] 2.2 Pass startup `secrets` into `ConfigManager._reload` so reloads preserve `llm_host`/`llm_api_key` — Note: implemented at the `resolve_output_sink`/MQTT-reload-callback level; verify `ConfigManager._reload` itself threads `secrets` through `load_config` before archiving (see Known Gaps below)
- [x] 2.3 Make web-UI config saves call the reload path unconditionally (remove the `if self._config_manager` guard dependency on the flag)
- [ ] 2.4 Fix redundant `except (ConfigError, Exception)` in config_manager.py — not done; low-risk leftover, safe to pick up anytime
- [x] 2.5 Targeted tests: existing `tests/test_config.py` reload/watcher tests pass unchanged

## 3. LiveKit worker supervision + watchdog coverage (D3, D4)

- [x] 3.1 Wrap the LiveKit worker loop in try/except with `logger.exception`, dashboard event, and 5→60 s backoff restart (reset after 10 min healthy)
- [x] 3.2 Handle missing-env (`require_env`) as CRITICAL log + stop retrying, daemon stays alive
- [x] 3.3 Move `require_env`-dependent `browser_join_url()` out of the unprotected first line of `_async_main`
- [x] 3.4 Add watchdog ping helper invoked from idle trigger-wait loop, participant polling, and in-session wait; keep heartbeat-freshness gating — implemented as an independent background task, superseding the original per-iteration design
- [x] 3.5 Stamp the STT heartbeat around dispatch await points so legitimate ≤90 s dispatches stay fresh
- [x] 3.6 Add commented `Type=notify` + `WatchdogSec=90` block with instructions to `setup/serena.service`
- [x] 3.7 Guard `int(os.environ.get("WATCHDOG_USEC", "0"))` against malformed values

## 4. SIGTERM graceful teardown (graceful-shutdown delta)

- [x] 4.1 Install a SIGTERM handler in the web-server run path that triggers the ordered teardown (STT stop, MQTT offline, LiveKit disconnect, watcher stop, display clear)
- [ ] 4.2 Verify `systemctl --user restart serena` performs clean teardown — requires on-board `systemctl` access; deferred to task 9.3

## 5. STT capture recovery (D5, D6, D7)

- [x] 5.1 Add `stt.capture_stall_secs` config (default 30); in `_iter_gated_audio`, ERROR-log and return when the alive process delivers no bytes for that long
- [x] 5.2 Broaden model-load exception handling in `run_stt_worker` to `except Exception` with 10→60 s backoff retry instead of thread exit
- [x] 5.3 Add backoff to web `_stt_watchdog_loop` restarts and pass the chained `_on_stt_event` callback (display keeps receiving events after restart)
- [x] 5.4 Add a change-generation signal bumped by config reload and AudioWatcher reconnect; recognition loop exits to the outer loop within one chunk when it changes (generalized `gst_profile_change_event` via new `signal_capture_restart()`)
- [x] 5.5 STT teardown: escalate `terminate()` → `kill()` after bounded wait
- [x] 5.6 Targeted tests: `tests/test_capture_stall.py` (stall detection, silence-within-threshold, disabled-threshold)

## 6. STT correctness bugs (D8, D9, D10)

- [x] 6.1 Extract shared GStreamer stage builder (`_build_dsp_stages`) used by both `_build_pipeline_string` and `_build_gst_launch_cmdline`; restore the missing `audioconvert` before `webrtcdsp` in the gst-launch path
- [x] 6.2 Fix trigger-dump buffer budget (mono: `dump_secs * 16000 * 2`) and write 1-channel WAVs
- [x] 6.3 Apply the confidence gate to the `finalize()` tail in `stt_capture.py` reply capture
- [x] 6.4 Change adaptive-RMS clamp to profile-as-floor (`max` semantics) and align the comment — **on-board `serena-stt --play` replay validation (per the design's stated gate) not yet performed; no dev-board access in this session** — flagged for verification before wide deployment
- [x] 6.5 Targeted tests: `tests/test_gst_highpass_audioconvert.py`, `tests/test_trigger_dump.py`, `tests/test_capture_finalize_gate.py`

## 7. Audio subprocess/playback hardening (D11, D12)

- [x] 7.1 Add `timeout=5` + WARNING on `TimeoutExpired` to `amixer` in `_restore_hw_pcm` and `pactl` in `set_input_gain`
- [x] 7.2 Add SIGTERM→SIGKILL escalation to `_run_capture_tool`'s capture branch
- [x] 7.3 `play_wav_file`: remove `except Exception: pass` + `stderr=DEVNULL`; log returncode/stderr on failure
- [x] 7.4 Merge `_play_raw` into `_play_array` (frombuffer/reshape), unifying error handling
- [x] 7.5 Add `invalidate_output_sink()`; call from `AudioWatcher._check_and_enforce` on device (re)connect; `resolve_output_sink` re-resolves lazily when invalidated
- [x] 7.6 Targeted tests: `tests/test_audio_hardening.py`

## 8. Cleanup (drift removal)

- [x] 8.1 Delete `setup/99-switch-on-connect.conf`
- [x] 8.2 Remove dead code: `set_stt_gated_flag`, `get_pipewire_device` cache + `invalidate_pipewire_device_cache` call, `subscribed_tracks`, duplicate imports and duplicated `sd.query_devices` calls in client.py — done. Unused `pulse`/`output_spec` parameters on `set_output_volume` intentionally left alone (public-ish signature with cross-module callers; not worth the churn/risk in this pass)
- [x] 8.3 Removed `_graceful_shutdown` (dead code, zero callers); SIGTERM teardown implemented inline in `WebServer.run()` instead (task 4.1). **Known gap**: the pre-existing (unmodified) graceful-shutdown requirements for the `.py` source-watcher restart and the web-dashboard "restart" button still call `os.execv()` directly without ordered teardown — out of this change's explicit scope, flagged as a follow-up
- [x] 8.4 Guard fire-and-forget tasks (`remove_track`, `play_call_start`) with a shared `_log_task_exception` done-callback
- [x] 8.5 CLAUDE.md reviewed — no changes needed; documented hot-reload behavior already matched the now-implemented behavior

## 9. Final validation

- [x] 9.1 Lint (`ruff check`/`ruff format --check`) clean on all changed files; full test suite: 485 passed, 2 pre-existing failures unrelated to this change (`test_persistent_history.py` — confirmed failing on the clean `one-model` tree before this change via `git stash`)
- [x] 9.2 `task eval` — 100 % precision / 100 % recall, 35/35 cases, unchanged
- [ ] 9.3 On-board smoke — **requires physical board access, not available in this session**: `task audio:doctor`, live config edit reload, `systemctl --user restart serena` clean teardown, MQTT discovery (if broker configured), SP92-direct gst-launch config starts without link failure
- [ ] 9.4 24 h dev-board soak with `WatchdogSec=90` manually enabled — **requires physical board access, not available in this session**
