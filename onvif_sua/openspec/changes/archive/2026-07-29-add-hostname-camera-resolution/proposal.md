## Why

The cameras will no longer have static IP addresses — the only stable identifier the operator has is each camera's ONVIF device hostname. Today `settings.yaml` pins each camera to a literal `ip`, so a DHCP lease change silently breaks the ONVIF connection and the Dahua CGI stream with no recovery. We need to address cameras by hostname and keep the resolved IP current automatically.

## What Changes

- Add an optional `hostname` field to each `cameras.list` entry in `settings.yaml`. An entry now supplies **either** `ip` (static, exactly as today) **or** `hostname`, plus the required `name`. Static-IP entries keep working unchanged (non-breaking).
- On boot, resolve every hostname-configured camera to its current IP by scanning the configured subnet, querying each responding ONVIF device's `GetHostname()`, and matching it (case-insensitively) to the configured hostname.
- Cache the resolved IP at runtime only ("temporarily") — the resolved address is never written back into `settings.yaml`; the hostname stays authoritative in the config file. This requires the `settings.yaml` mutation helpers to become hostname-aware: they all identify entries by IP today, which for a hostname entry silently matches nothing — so a GUI rename would *append* a second entry carrying the resolved IP, and a GUI remove would delete nothing.
- Re-run the resolution scan every 10 minutes as a background task. If a hostname now resolves to a **different** IP, tear down the old per-camera worker and re-spawn it on the new IP (reusing the existing teardown/respawn primitives).
- On resolution failure, **keep the last known IP** and leave the worker running (resilient to transient blips). A hostname that has never resolved is retried on the same 10-minute cadence until it appears.
- If **two or more devices report the same hostname** (identical cameras on factory defaults), treat it as unresolved rather than picking one, and never migrate a running worker on such a scan. A wrong pick would monitor one room while announcing another room's name — an unresolved camera fails loudly instead, and the ambiguity clears by itself once the devices are given distinct hostnames.
- Keep the GUI rename working for hostname cameras. Renaming a camera sets its **ONVIF device hostname** (`SetHostname`) — the same value this feature resolves on — so the rename now rewrites the entry's `hostname` alongside its `name` in one save, using the hostname the device actually reports back. A rename that would make one camera answer to another entry's configured `hostname` is rejected before the device is touched. `name` stays the sole MQTT/Home Assistant/Serena identity; `hostname` is only the discovery key.
- Update `settings.yaml`, `.env.example`/config docs, and `README.md` to document the new `hostname` field and the resolution behavior.

## Capabilities

### New Capabilities
- `hostname-camera-resolution`: Resolving a camera configured by ONVIF hostname to its current IP via a subnet scan at boot, caching the resolved IP at runtime, periodically re-resolving every 10 minutes, and migrating the running worker when the IP changes — while leaving static-IP configuration behavior intact.

### Modified Capabilities
<!-- No spec-level requirement changes to existing capabilities. The new periodic
     resolution scan reuses scan.py probing but is a distinct capability; it does
     not change the manual-scan control requirements in `scan-control`. -->

## Impact

- **Config parsing**: `config.py` `_load_static_cameras()` — accept `hostname` as an alternative to `ip`; validation/uniqueness rules extended to cover hostname entries.
- **Config mutation helpers**: `config.py` `_config_add_camera`, `_config_remove_camera`, `_config_name_conflict`, `_name_voice_collision` — all four match entries with `str(e.get("ip")) == ip`, which renders `"None"` for a hostname entry and silently treats it as a different camera. Take an optional `hostname` and match on it; the reverse IP→hostname lookup lives in `state.py` and is passed down by the caller (`config.py` cannot import `state` — that direction is already taken).
- **Rename / remove paths**: `web/routes.py` `api_rename_camera` (routes.py:96-178) — pre-flight hostname-collision rejection before `SetHostname` (routes.py:136), persist the device-reported hostname, re-key the runtime cache. `api_remove_camera` (routes.py:234) — resolve the hostname so the entry is actually deleted, and purge its cache entry.
- **Worker lifecycle**: `worker.py` — new `_hostname_resolve_loop()` background task created in `_main_loop_coro` (alongside the existing periodic loops at ~lines 1111-1113); startup wiring to resolve hostnames before spawning workers; IP-change migration via existing `_teardown_camera(old_ip)` + `_spawn_worker(new_info)`.
- **Scanning**: `scan.py` — a reusable probe that returns each device's ONVIF hostname so the resolution loop can match by hostname (the sweep infrastructure and `GetHostname()` call already exist).
- **Runtime state**: `state.py` — a cache mapping configured hostname → last-resolved IP, guarded by `state._lock`.
- **Config files & docs**: `settings.yaml`, `.env.example`, `README.md`, `serena_sua_config.md`.
- **Tests**: new pytest coverage for hostname parsing and the resolve/IP-change path (monkeypatching the resolver); `scan.py` currently has no tests.
- **Dependencies**: none added — stdlib + existing `onvif-zeep-async` cover it.
