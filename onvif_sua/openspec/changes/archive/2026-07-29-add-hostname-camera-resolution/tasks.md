## 1. Config schema — accept `hostname` as an alternative to `ip`

- [x] 1.1 In `config.py` `_load_static_cameras()` (around line 536), read both `ip` and `hostname` from each `cameras.list` entry; require `name` plus exactly one of `ip`/`hostname`, and log-and-skip entries with neither or both.
- [x] 1.2 Carry the `hostname` through into the returned camera dict (e.g. `{"name", "hostname"}` for hostname entries, `{"name", "ip"}` for static entries) without treating hostname as an IP.
- [x] 1.3 Extend the uniqueness checks so hostnames are unique across entries and a resolved/declared IP cannot collide with another entry; mirror the existing duplicate-drop + diagnostic behavior.
- [x] 1.4 Ensure `_save_settings_yaml()` (config.py:338-393) preserves `hostname` entries verbatim and never writes a runtime-resolved `ip` back into a hostname entry.

## 1b. Config mutation helpers — hostname-aware entry lookup

Shared by the rename (§4b) and remove paths. **Import constraint:** `config.py` must NOT import `state` — `state.py` imports config scalars and documents itself as the leaf module (`state.py:1-3`), so the reverse would be circular. Resolve the IP→hostname mapping in the **caller** (`web/routes.py`, which already imports both) and pass the hostname into these helpers as an optional argument, defaulting to `None` for static-`ip` callers.

- [x] 1b.1 Add the resolved-IP→hostname reverse lookup to `state.py` alongside task 3.1's map (e.g. `hostname_for_ip(ip) -> str | None`), reading under `state._lock`.
- [x] 1b.2 Audit every `str(e.get("ip"))` comparison in `config.py` — a hostname entry has no `ip`, so this renders the literal `"None"` and silently classifies the entry as a different camera. Affected sites: `_name_voice_collision` (config.py:187), `_config_name_conflict` (config.py:586), `_config_add_camera`'s name-uniqueness loop (config.py:625) and its update loop (config.py:638), `_config_remove_camera` (config.py:658). Replace each with a match that accepts an optional `hostname` and compares `e.get("hostname")` for hostname entries.
- [x] 1b.3 `_config_add_camera(ip, name, port, hostname=None)` — when `hostname` is given, locate the entry by `hostname` and update it in place (never `lst.append` a `{ip, name}` entry, config.py:642); write `name` and `hostname` in the same `_save_settings_yaml()` call (see 4b.3 for which hostname value).
- [x] 1b.4 `_config_remove_camera(ip, hostname=None)` — when `hostname` is given, drop the entry matching that `hostname` and return True. Wire `web/routes.py` `api_remove_camera` (routes.py:234) to resolve the hostname first and pass it, then purge the hostname's cache entry from `state.py` after a successful removal.
- [x] 1b.5 `_config_name_conflict(ip, name, hostname=None)` and `_name_voice_collision(ip, name, hostname=None)` — skip the caller's *own* entry when it is a hostname entry (today it is never skipped, so a hostname camera cannot be renamed to any name normalising like its current one, and the error reads "…coincide con la telecamera None"). When a genuine conflict is found against a hostname entry, return that entry's `hostname`/`name` for the diagnostic instead of `str(e.get("ip"))`.
- [x] 1b.6 Confirm `_configured_camera_names()` (config.py:590-606) needs no change — it reads only `e["name"]`, which hostname entries carry.

## 2. Resolver — subnet scan that matches ONVIF hostname

- [x] 2.1 In `scan.py`, factor `_probe_ip()` so the per-host probe returns the device's ONVIF hostname (`GetHostname().Name`, trimmed) alongside `{ip, name, port}` — reuse the existing `GetHostname()` call at scan.py:70-78.
- [x] 2.2 Add a resolver function that runs one subnet sweep over `scan.subnet` and returns a mapping of `{configured_hostname_lower: ip}` for every wanted hostname found (case-insensitive, trimmed match), reusing the existing concurrency semaphore.
- [x] 2.3 Log online devices whose ONVIF hostname matched no configured entry (diagnostic aid), and log hostnames that resolved to a duplicate IP. Define "keep first" as **lowest index in `cameras.list`**, not scan completion order — `asyncio.gather` ordering must not decide which entry wins.
- [x] 2.4 Make the resolver return **all** candidate IPs per wanted hostname, not the first match, so ambiguity is detectable. A hostname with ≥2 candidates SHALL be reported as ambiguous rather than resolved — do not collapse it to one IP inside the resolver.
- [x] 2.5 Add candidate-set-change logging: remember the last logged candidate set per ambiguous hostname and emit the diagnostic only on first detection or when that set changes (a 10-minute cadence would otherwise print ~144 identical lines/day per hostname). Apply the same dedupe to 2.3's unmatched-device log.

## 3. Runtime state — cache resolved IPs

- [x] 3.1 In `state.py`, add a hostname→last-resolved-IP map (and the reverse lookup needed for migration), guarded by `state._lock`.
- [x] 3.2 Provide small accessor helpers to read/update the map atomically.

## 4. Worker lifecycle — boot resolution + periodic re-resolution

- [x] 4.1 In `worker.py` `_main_loop_coro()` startup (around lines 1130-1139), for hostname-configured cameras defer `_spawn_worker` until the hostname resolves; static-`ip` cameras spawn immediately as today.
- [x] 4.2 Add `_hostname_resolve_loop()` following the existing periodic-loop pattern (see `_detection_ok_republish_loop`), running an immediate first sweep at boot then `await asyncio.sleep(600)` each iteration.
- [x] 4.3 Register the loop via `asyncio.create_task(_hostname_resolve_loop(), name="hostname-resolve")` alongside worker.py:1111-1113.
- [x] 4.4 On each tick, resolve all hostname cameras; for a hostname whose resolved IP differs from its currently-running worker IP, call `_teardown_camera(old_ip)` then `_spawn_worker(new_info)` with the new IP and the preserved `name`.
- [x] 4.5 On a hostname that fails to resolve, keep the last-known IP and leave a running worker untouched; a never-resolved hostname simply spawns no worker and is retried next tick.
- [x] 4.5b Treat an **ambiguous** hostname (§2.4, ≥2 candidates) exactly like a failed resolution: never spawn, never migrate, never update the cached IP — including when the running worker's IP is not among the candidates. Do not pick a candidate.
- [x] 4.6 Ensure the resolution loop does NOT touch the manual-scan `scan_active` flag or the stop-scan signal (keep its bookkeeping separate from `scan-control`).

## 4b. Rename path — keep the configured hostname in sync with the device

- [x] 4b.1 In `web/routes.py` `api_rename_camera`, resolve the target IP to its configured hostname (§1b.1) and pass it to the §1b helpers so the pre-flight checks and the save all act on the existing hostname entry. The entry-lookup and `"None"`-comparison fixes themselves live in §1b.
- [x] 4b.2 In `web/routes.py` `api_rename_camera` (routes.py:96-178), add the pre-flight rejection: reject with 409 when `new_name` equals another entry's configured `hostname` (trimmed, case-insensitive — same comparison as the resolver), before the `SetHostname` call at routes.py:136. Allow a match against the renamed camera's own `hostname`.
- [x] 4b.3 After the existing verification read (routes.py:141-156), write the **device-reported** hostname into the entry; when `actual_name is None` (read failed), write `new_name` and log a warning naming the old and new hostname.
- [x] 4b.4 When the post-`SetHostname` save fails, return the rename as failed and log the device's new hostname at warning level so the entry can be repaired by hand.
- [x] 4b.5 Re-key the `state.py` hostname→IP cache from the old to the new hostname under `state._lock` (task 3.1's map), leaving no entry under the old key. Do NOT call `_teardown_camera`/`_spawn_worker` — the IP has not changed.
- [x] 4b.6 Confirm a static-`ip` rename is untouched by all of the above (no `hostname` key added, same behavior as today).

## 5. Config files & documentation

- [x] 5.1 Update `settings.yaml` comments and add a commented hostname example to `cameras.list`.
- [x] 5.2 Document the `hostname` field (must equal the camera's ONVIF device hostname, not a DHCP/DNS name), the 10-minute re-resolution, and keep-last-IP behavior in `README.md` and `serena_sua_config.md` (and `.env.example` if relevant).
- [x] 5.3 Document the rename interaction in `README.md` / `serena_sua_config.md`: renaming a camera sets its ONVIF device hostname, so renaming a hostname-configured camera also rewrites its `hostname:` in `settings.yaml` (the two converge, and an original factory hostname is not recoverable from the config afterwards — it is logged); a rename that collides with another entry's `hostname` is refused. State that `name` is the MQTT/Home Assistant/Serena identity and `hostname` is only the discovery key.

## 6. Tests

- [x] 6.1 Add config-parsing tests: hostname-only accepted, ip-only unchanged, neither/both rejected, uniqueness enforced (monkeypatch nothing — pure parser).
- [x] 6.2 Add resolver tests that monkeypatch the subnet-sweep/probe to return synthetic devices and assert the correct hostname→IP mapping (case-insensitive match, no-match, collision).
- [x] 6.2b Add ambiguity tests with synthetic devices: (a) two devices reporting one wanted hostname → reported ambiguous, no IP resolved, both candidates logged; (b) same, with a worker already running → worker untouched, no teardown/respawn, cached IP unchanged; (c) same, with the running IP *not* among the candidates → still no migration; (d) the ambiguity clears on the next tick once one device reports a different hostname, and the worker is then spawned; (e) the diagnostic is emitted once for an unchanged candidate set across two ticks, and again when the set changes; (f) two configured hostnames resolving to one IP → the lower `cameras.list` index wins, asserted under both probe-completion orders.
- [x] 6.3 Add a worker-migration test: simulate a resolved IP change and assert `_teardown_camera(old_ip)` + `_spawn_worker(new_info)` are invoked with the new IP and preserved name; and a failure case asserting the running worker is left intact.
- [x] 6.4 Add rename tests (monkeypatch `ONVIFCamera` so `SetHostname`/`GetHostname` are fakes — no device needed): (a) rename of a resolved hostname camera rewrites both `hostname` and `name` in one save and adds no `ip` key; (b) device reports a different hostname than requested → the reported value is persisted; (c) verification read fails → requested name persisted + warning; (d) rename colliding with another entry's `hostname` is rejected 409 and `SetHostname` is never called; (e) rename to the camera's own `hostname` proceeds; (f) the cache is re-keyed and no teardown/respawn occurs; (g) a static-`ip` rename gains no `hostname` key.
- [x] 6.5 Add a post-rename resolution test: after a rename, the next resolver tick matches the rewritten hostname to the same IP and spawns no second worker.
- [x] 6.6 Add config-helper tests (pure `_settings_doc` manipulation, no device, no loop): (a) `_config_add_camera` with a hostname updates the existing entry and leaves `len(cameras.list)` unchanged — regression test for the `lst.append` duplicate; (b) `_config_remove_camera` with a hostname returns True and drops the entry; (c) `_config_name_conflict` does not report a hostname entry as conflicting with itself; (d) `_name_voice_collision` allows renaming a hostname camera to a case/separator variant of its own name; (e) a genuine conflict against a hostname entry reports that entry's `hostname`, never the string `"None"`; (f) all four helpers behave identically to today for static-`ip` entries.
- [x] 6.7 Add a removal-durability test: remove a resolved hostname camera, then run a resolver tick with the device still online and reporting its hostname, and assert no worker is spawned (the entry is gone) and the cache holds no entry for it.
- [x] 6.8 Run `uv run pytest tests/` and confirm the suite passes.

## 7. Sync & finalize

- [x] 7.1 Mirror any edited top-level duplicate `*.py` file into the canonical `onvif_sua/` package copy (config.py, scan.py, worker.py, state.py **and web/routes.py** are all byte-identical duplicates) or confirm only the packaged copy needs editing.
- [x] 7.2 Run `openspec validate add-hostname-camera-resolution` and confirm it reports valid.
