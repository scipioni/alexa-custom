## Context

Cameras are configured as static entries in `settings.yaml` under `cameras.list`, each `{ip, name}`. The parser `_load_static_cameras()` (`config.py:489-572`) reads `ip` at line 536 and requires both `ip` and `name`, enforcing uniqueness on each. At runtime the **IP string is the primary key** for every structure in `state.py` — `_cameras`, `_worker_tasks` (task name `cam-{ip}`), `_rule_tasks`, `_auth_failed`, `_removed_ips`, and the Dahua CGI thread/stop-event maps. Only two code sites actually consume the address: `connect.py:155` (`ONVIFCamera(ip, port, user, pwd, ...)`) and the Dahua CGI URL at `worker.py:398/402`; both accept a hostname string as-is but every caller treats the value as an IP.

`scan.py` already performs a manual, operator-triggered subnet sweep: `_subnet_scan_once()` expands the configured CIDR (`scan.subnet`), probes each host concurrently under a semaphore, and `_probe_ip()` validates ONVIF and calls `dev.GetHostname()` (`scan.py:70-78`) — currently only to derive a display *name*. There is a well-worn periodic-loop pattern (`asyncio.create_task(...loop())` in `_main_loop_coro`, `worker.py:1111-1113`; `while True: await asyncio.sleep(interval)`), and teardown/respawn primitives (`_teardown_camera(old_ip)` at `worker.py:872-900`, `_spawn_worker(info)` at `worker.py:856`). No DNS library is bundled; the ONVIF device hostname is set on the camera and is not assumed to be in DNS.

## Goals / Non-Goals

**Goals:**
- Let an operator configure a camera by ONVIF `hostname` instead of a static `ip`, keeping `name` required.
- Resolve hostname → current IP by subnet scan + ONVIF `GetHostname()` match at boot, before spawning the worker.
- Re-resolve every 10 minutes; when a hostname's IP changes, migrate the running worker to the new IP.
- Keep static-`ip` configuration behavior byte-for-byte unchanged (non-breaking).
- Keep the resolved IP in memory only — never persist it to `settings.yaml`.
- Keep the GUI rename working for hostname-configured cameras: because renaming sets the device's ONVIF hostname, the rename also rewrites the entry's `hostname` so the camera stays resolvable.

**Non-Goals:**
- No DNS/mDNS resolver path (explicitly rejected — see Decisions).
- No change to the manual GUI rescan / `scan-control` behavior (`scan_active`, stop button).
- No re-keying of runtime structures away from IP — the resolved IP remains the runtime key.
- No per-camera configurable interval or subnet; the 10-minute cadence and existing `scan.subnet` are reused.

## Decisions

### Resolution mechanism: subnet scan + ONVIF `GetHostname()` match
Reuse the existing `scan.py` sweep to probe the configured subnet and match each responding device's ONVIF `GetHostname().Name` (case-insensitive, trimmed) against the configured hostname. Factor the per-host probe so it returns the device's ONVIF hostname alongside `{ip, name, port}`, and add a resolver that maps a set of wanted hostnames to their current IPs in one sweep (so N cameras cost one scan, not N).

- **Why not DNS/mDNS (`socket.getaddrinfo`)?** The identifier the operator controls is the camera's ONVIF device hostname, which is not guaranteed to be registered in the LAN DNS or answer mDNS. Scan + ONVIF match works regardless of name resolution infrastructure and reuses code that already queries `GetHostname()`.
- **Trade-off accepted:** a full subnet probe is slower than a DNS lookup and adds scan traffic every 10 minutes; acceptable on a /24 home subnet with the existing concurrency semaphore.

### Config schema: `hostname` is an alternative to `ip`
A `cameras.list` entry MUST have `name` and MUST have exactly one of `ip` or `hostname`. Static-`ip` entries are parsed and behave exactly as today. Hostname entries carry the hostname through parsing; the resolved IP is attached at runtime, not stored in config. Uniqueness is enforced across the resolved/declared address space and across hostnames so two entries can't collide.

### Runtime keying stays IP-based; IP change = teardown + respawn
The resolved IP remains the dictionary key. On boot, resolve hostname entries to an IP before calling `_spawn_worker`. When a periodic re-resolution yields a **different** IP for a hostname, call `_teardown_camera(old_ip)` then `_spawn_worker(new_info)` with the new IP — reusing existing primitives rather than introducing hostname-keyed state. A hostname→last-resolved-IP map lives in `state.py` under `state._lock`.

- **Why not re-key everything by hostname?** IP-keying is pervasive and load-bearing; re-keying is a large, risky refactor for no functional gain. Teardown+respawn is the smallest correct change.

### The ONVIF hostname is not immutable — rename rewrites the config entry

`POST /api/cameras/{ip}/rename` (`web/routes.py:136`) sets the camera's ONVIF hostname via `SetHostname({"Name": new_name})`, verifies it with `GetHostname()`, and persists the display name. The device stores **one** string, and the GUI owns it — so `GetHostname().Name`, the value this change resolves on, is exactly the value the rename endpoint overwrites. Left alone, any GUI rename silently invalidates a hostname entry: the running worker survives on the cached IP, and the camera only fails to come back at the next restart or lease change.

Chosen resolution: **the rename rewrites the entry's `hostname` in the same transaction as its `name`.** The device stays the source of truth and the operator keeps the rename feature.

- **Why not reject the rename for hostname cameras (409)?** It is the simpler rule, but renaming is the only way to set a camera's display name in this service, and the name is the MQTT/Home Assistant/Serena identity. Blocking it would mean a hostname-configured camera can never be renamed — a real capability regression, and one that pushes operators back to static IPs.
- **Write what the device reports, not what was requested.** The endpoint already performs a verification `GetHostname()` read (`routes.py:141-156`). Writing the *reported* value makes the entry self-healing when a device normalises or truncates the name, and collapses the "verified is False" case from "config now unresolvable" to "config matches reality". Only a failed verification read leaves a guess, and that case is logged.
- **`name` and `hostname` stay independent keys.** Divergence is legitimate — factory hostname plus friendly room name — so the schema keeps both. A rename converges them (the device can hold only one string), which means an operator who renames loses the original device hostname; the pre-rename value is logged for rollback.
- **New cross-entry hazard:** since a rename sets a device hostname, renaming camera A to camera B's configured `hostname` would make A answer B's resolution. Pre-flight check rejects that before the device is touched, using the same trimmed/case-insensitive comparison as the resolver.
- **Cache re-keying is not optional.** The `state.py` hostname→IP cache is keyed by the *configured* hostname. Leaving a stale key after a rename means the next tick sees the new hostname as never-resolved and cannot compare against the running worker's IP — which is how a duplicate worker gets spawned on an IP that already has one. The rename moves the cache entry; the worker is untouched because the IP did not change.

### Config mutation helpers must match a hostname entry, not the string `"None"`

The web API addresses cameras by runtime IP, and every `settings.yaml` mutation helper matches entries with `str(e.get("ip")) == ip`. A hostname entry has no `ip`, so that expression renders the literal `"None"` — never equal to a real IP. The failure is uniform and silent: each helper concludes "this is some other camera."

- `_config_add_camera` (`config.py:638`) finds no match and **appends** `{ip: <resolved>, name}` (`config.py:642`) → two entries for one camera, the resolved IP persisted against the never-persist requirement, and a duplicate-name rejection at next load that drops both.
- `_config_remove_camera` (`config.py:658`) matches nothing and returns `False` → the entry survives, and because the entry is what drives resolution, the next tick respawns the camera **within one interval**. The camera comes back by itself; no restart needed to resurrect it.
- `_config_name_conflict` (`config.py:586`) and `_name_voice_collision` (`config.py:187`) never skip the camera's own hostname entry, so a hostname camera cannot be renamed to any name normalising like its current one — including a case-only change — and the operator sees *"coincide con la telecamera None"*.

Fix: pass the configured hostname alongside the IP and match on it when present.

**Import direction constrains where the lookup lives.** `state.py` imports config scalars and documents itself as the leaf module "so every other module can import it without cycles" (`state.py:1-3`); `config.py` imports no runtime state. So `config.py` cannot read the hostname→IP cache. The reverse lookup lives in `state.py`, and the **caller** (`web/routes.py`, which already imports both) resolves IP→hostname and passes it down as an optional argument. Helpers keep their current signature for static-`ip` callers, so nothing existing changes behavior.

`_configured_camera_names()` (`config.py:590-606`) reads only `e["name"]` and needs no change.

### Periodic resolution loop
Add `_hostname_resolve_loop()` following the established pattern, created in `_main_loop_coro` next to the other periodic tasks. It performs one subnet sweep per tick (boot tick immediate, then every 600 s), resolves all hostname-configured cameras, and applies any IP changes. Boot resolution happens before/at first tick so hostname cameras that resolve start promptly; those that don't resolve at boot are simply retried each tick.

### Ambiguous hostname: refuse rather than guess

Two responding devices can report the same ONVIF hostname — identical cameras on factory defaults are the common case, and `SetHostname` (see above) makes operator-created duplicates possible too. The resolver treats "two candidates" as unresolved rather than picking one, and never migrates a running worker on an ambiguous scan.

- **Why not pick deterministically (e.g. lowest IP)?** It was the first instinct: a deterministic tiebreak keeps the camera running and avoids flapping. It was rejected because it trades a *loud* failure for a *silent wrong* one. `name` is the room identity on every alarm, MQTT topic, HA entity and Serena phrase, so a wrong pick monitors the bathroom while announcing "sensore uomo a terra cucina attivo". The operator believes the kitchen is covered; a fall there is never reported, and a fall in the bathroom is announced as the kitchen. An unresolved camera, by contrast, has no worker, shows as down on the dashboard, and is announced as faulty by the Serena fault driver — the operator finds out in minutes. In a fall-detection system, loud-and-wrong beats quiet-and-wrong.
- **Why prefer the incumbent when a worker is already running?** Stability. Without it, two matching devices would make the resolver alternate between them, and each alternation is a teardown + respawn — which drops the camera's alarm state and republishes its availability. Keeping the incumbent also means introducing a duplicate device on the network can never knock a working camera offline.
- **Recovery is self-service and needs no restart.** The hostname is retried every tick, so renaming one of the two devices (via the manual scan + rename flow) clears the ambiguity on the next sweep.
- **Log volume.** On a 10-minute cadence an unconditional diagnostic would print ~144×/day per ambiguous hostname. Emit on first detection and on any change to the candidate set — the same treatment task 2.3's unmatched-device log needs.

### Failure handling: keep last known IP
If a hostname fails to resolve during a periodic tick, retain the previously resolved IP and leave the worker running (transient DNS/network/scan blips must not drop a working camera). A hostname that has *never* resolved has no worker yet and is retried on the next tick until it appears; this is surfaced in status/logs but is not an error state.

## Risks / Trade-offs

- **ONVIF hostname ≠ operator's expected hostname** → The match is against `GetHostname().Name` exactly as the device reports it; document that the `settings.yaml` `hostname` must equal the ONVIF device hostname (not a DHCP/DNS name). Log unmatched-but-online devices at boot to aid diagnosis.
- **A GUI rename changes the identity being resolved** → Handled by rewriting the entry's `hostname` in the same save as its `name` (see Decisions). Residual risk: the operator loses the original device hostname on the first rename, and a rename whose verification read fails leaves an unverified `hostname` in the config. Both are logged; neither drops a running camera, because the rename never touches the worker.
- **A rename could hijack another entry's hostname** → Pre-flight rejection before `SetHostname`, using the resolver's own trimmed/case-insensitive comparison.
- **Stale hostname→IP cache key after a rename** → The rename re-keys the cache under `state._lock`. Without this the next tick treats the new hostname as never-resolved and can spawn a second worker on the running IP.
- **Two entries resolve to the same IP (hostname reused / device answers for two names)** → Log and drop the collision, keeping the entry that appears **first in `cameras.list`** — "first" must be the config order, not scan completion order, or the winner changes tick to tick. Enforced in the resolver, not the parser (the parser has no resolved IPs to compare).
- **Two devices report one wanted hostname** → Treated as unresolved rather than picked (see Decisions); a running worker is never migrated on an ambiguous scan.
- **Scan overlaps the manual GUI rescan** → Both sweep the same subnet; the resolution loop is independent of the `scan_active` manual-scan flag and must not clobber it. Keep the resolution scan's bookkeeping separate from the manual `scan_active` signal so the stop-scan UI is unaffected.
- **IP flaps between two addresses each tick** → Teardown/respawn churn. Mitigation: only migrate when the newly resolved IP differs from the currently *running* IP (not merely from a prior scan artifact), and treat a failed resolve as "no change".
- **Boot slowness** → A hostname camera can't start until the first sweep completes. Mitigation: run the first sweep immediately at startup rather than waiting a full interval.

## Migration Plan

- Purely additive: existing `settings.yaml` files with `ip` entries need no change and behave identically.
- To adopt: replace an entry's `ip:` with `hostname:` (keep `name:`), restart the service. First boot sweep resolves it. Set `hostname:` to what the camera currently reports for `GetHostname()` — if the camera was ever renamed through this GUI, that is its display name.
- Rollback: revert the entry to `ip:` (the last-resolved IP is logged), restart. No schema migration, no persisted state to unwind.
- One-way step to be aware of: the first GUI rename after adoption sets `hostname` equal to the new `name`, so an original factory device hostname is not recoverable from the config afterwards. The pre-rename value is logged.

## Open Questions

- **Resolved (log-only for now):** unmatched / not-yet-resolved hostnames are surfaced via log lines only, not `GET /api/status`. A per-camera `resolved`/`hostname` status field is deferred as a cheap follow-up if the dashboard needs it later.
