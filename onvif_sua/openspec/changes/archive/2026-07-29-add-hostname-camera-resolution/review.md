## Specification Review: add-hostname-camera-resolution

**Review Date**: 2026-07-28
**Reviewer Role**: Senior Software Architect
**Scope**: `openspec/changes/add-hostname-camera-resolution/specs/hostname-camera-resolution/spec.md`, `proposal.md`, `design.md`, `tasks.md` — validated against `onvif_sua/{config,scan,worker,state,connect}.py` and `onvif_sua/web/routes.py`

### First Time Right Probability: 30% (floor-capped; raw score -2%)

The spec is well-structured, scenario-complete and internally coherent about the *happy path*, but it was written against a mental model of the codebase that misses three load-bearing invariants: (a) `scan.py` is deliberately **manual-only** because a periodic multi-credential sweep is exactly the Dahua anti-intrusion lockout the whole codebase is architected to avoid, (b) the ONVIF device hostname is **not a stable identifier** — `POST /api/cameras/{ip}/rename` overwrites it via `SetHostname()`, and (c) the settings.yaml mutation helpers are **IP-keyed**, so the resolved IP gets persisted by the GUI path the spec never examines. Any of the three breaks the feature or the existing service in production.

**Completeness**: Requirements (Y) | Scenarios (Y) | Error handling (partial — resolution failure covered, auth/scan-safety/port/subnet failure not) | Data models (partial — config entry shape defined, `_static_cameras` runtime dict shape change unanalysed) | APIs (N — no requirement covers the existing camera REST endpoints)

---

## Defects by Severity

### Critical (Must Fix Before Implementation)

#### C1. [CRITICAL] Periodic subnet sweep violates the codebase's anti-intrusion invariant and bypasses the placeholder-password guard
**Dimension**: D3 (Security/Safety), D2 (Edge cases)
**Location**: spec.md:23-37 (Requirement "Hostnames are resolved… by scanning the subnet"), design.md:24-28, tasks.md:2.2 / 4.2 — vs `onvif_sua/scan.py:1-2,44,56,91,102`, `onvif_sua/worker.py:1119-1128`, `onvif_sua/state.py:29-66`
**Issue**: The spec mandates an unconditional subnet sweep every 600 s reusing `_probe_ip()`, which is an **authenticating** probe: `GetDeviceInformation()` at `scan.py:66` exists precisely because "update_xaddrs does NOT authenticate", and it runs once per credential in `_get_cred_fallbacks()` (`scan.py:56`). Three separate guards protect this today and the spec re-asserts none of them: (i) `scan.py:1-2` and `scan.py:97-99` declare the sweep "manual GUI rescan only — never automatic… this never runs on its own"; (ii) `scan.py:102` aborts the whole sweep when `_password_placeholder_flags()["scan"]` is set — "the scanner would try that wrong password against every host and could trip Dahua anti-intrusion lockout"; (iii) `state._AuthGate` (`state.py:29-66`) caps auth to ≤1 per 5 s per IP so "the three auth paths do not fire a synchronized burst that trips Dahua anti-intrusion lockout" — `scan.py` never calls it. All three live in the *caller* the resolve loop replaces, so reusing the probe (tasks.md:2.2) inherits the risk and none of the mitigation.
**Credential count (verified)**: `_get_cred_fallbacks()` yields **1 credential deduped by default, 2 when `SCAN_USER`/`SCAN_PASSWORD` differ from `CAMERA_*`** — `config.py:450` unconditionally sets `_cfg["cam_credentials"]` from the env pair (`config.py:445-446`), making `_DEFAULT_CREDS` (`admin`/`Admin123`) effectively unreachable. Lower magnitude than a multi-credential sweep, but `SCAN_PASSWORD` is a semantically distinct secret ("the manual-scan credential", `config.py:437-438`), so an operator who sets it ships a second wrong password at every host every tick.
**Impact**: The feature converts a one-shot, operator-gated, explicitly-guarded scan into a permanent background login sweep: 254 hosts × 1-2 credentials × 144 ticks/day ≈ 36k-73k auth attempts/day against every host on the LAN. On a board where `CAMERA_PASSWORD` is still `default_to_change` (the shipped state, `config.py:444`), `_main_loop_coro` refuses to start even one worker (`worker.py:1119-1128`) but the resolve loop would still sweep — the exact scenario that guard exists to prevent. Cameras get locked out by their own anti-intrusion feature; recovery requires physical/vendor intervention.
**Example**: Fresh deploy, `.env` not yet edited. Boot: zero workers (placeholder guard), then every 10 minutes 254 hosts are probed with `default_to_change` — both real cameras accumulate failed logins until they lock out. The dashboard shows "nessun worker avviato" and the operator has no signal that the service is actively locking the hardware.

#### C2. [CRITICAL] The ONVIF hostname is not a stable identifier — the service's own rename endpoint overwrites it
**Dimension**: D1 (Logical consistency)
**Location**: spec.md:23-25 (match on `GetHostname().Name`), design.md:5,46, proposal.md:8 — vs `onvif_sua/web/routes.py:136` (`dev.SetHostname({"Name": new_name})`), `onvif_sua/scan.py:70-78`
**Issue**: The design's premise is that "the only stable identifier the operator has is each camera's ONVIF device hostname" (proposal.md:3). In this codebase the ONVIF hostname **is** the display-name storage: `POST /api/cameras/{ip}/rename` writes the new display name into the device with `SetHostname()` (`routes.py:136`), verifies it with `GetHostname()`, and `_probe_ip()` uses `GetHostname().Name` as the discovered camera's `name` (`scan.py:70-78`). There is exactly one string on the device, and the GUI owns it. The spec therefore requires `settings.yaml` to carry both a `name` and a distinct `hostname` for values the device cannot hold separately, and never states the relationship between them.
**Impact**: (1) Any GUI rename of a hostname-configured camera silently invalidates its `settings.yaml` `hostname`. The running worker survives (keep-last-IP), so the breakage is invisible until the next restart or DHCP change — at which point the camera never comes back. (2) Conversely, `hostname` and `name` must in practice be the same string, making the new config key redundant and the two-key validation rule (spec.md:5, "exactly one of `ip`/`hostname`") arbitrary. No requirement, scenario, or risk entry addresses either.
**Example**: Entry `{hostname: STANZA_11, name: soggiorno}`. Boot resolves (device hostname is `STANZA_11`). Operator renames it to "cucina" in the GUI → `SetHostname("cucina")`. Ten minutes later the sweep finds no device reporting `STANZA_11`; keep-last-IP hides it. Next reboot + new DHCP lease: no match, no worker, no fall detection for that room, and the only diagnostic is a log line.

#### C3. [CRITICAL] The resolved IP *is* persisted — by `_config_add_camera`, which the spec never examines
**Dimension**: D1 (Logical consistency), D2 (Edge cases)
**Location**: spec.md:39-49 (Requirement "…never persisted to settings.yaml"), tasks.md:1.4 — vs `onvif_sua/config.py:609-646` (esp. `642`: `lst.append({"ip": ip, "name": name})`), `onvif_sua/config.py:649-663`, `onvif_sua/web/routes.py:168,215,234`
**Issue**: Task 1.4 guards only `_save_settings_yaml()` (a pure round-trip of `_settings_doc`, which indeed cannot invent an `ip`). The actual mutators are IP-keyed and reached from three REST endpoints:
- `_config_add_camera(ip, name, port)` matches entries with `str(e.get("ip")) == ip` (`config.py:638`). A hostname entry has no `ip`, so no match → line 642 **appends a brand-new `{ip: <resolved_ip>, name: …}` entry** and calls `_save_settings_yaml()`. Called on every rename (`routes.py:168`) and every save (`routes.py:215`).
- `_config_remove_camera(ip)` filters on `str(e.get("ip")) == ip` (`config.py:658`) → returns `False` for a hostname entry; `routes.py:234` tears the worker down at runtime but the config entry survives.

**Impact**: Two guaranteed failures. (1) The stated invariant "the saved file… does not contain a resolved `ip` for it" (spec.md:47-49) is violated by the ordinary rename flow, and settings.yaml ends up with **two entries for one physical camera** (one `hostname:`, one `ip:`) → duplicate-name rejection at next boot drops *both* (`config.py:547-552`), i.e. the camera disappears entirely. (2) Removing a hostname camera from the GUI reports success but the camera returns on restart.
**Example**: `{hostname: STANZA_11, name: soggiorno}` resolves to 192.168.1.122. Operator renames to "salotto" → settings.yaml now holds `{hostname: STANZA_11, name: soggiorno}` **and** `{ip: 192.168.1.122, name: salotto}`. Restart → both entries load; if the operator ever renames back, duplicate-name poisoning drops both and the room loses fall detection.

### High (Likely to Cause Problems)

#### H1. [HIGH] Worker migration destroys the camera's active alarm state and publishes a retained MQTT "off"
**Dimension**: D2 (Edge cases), D1
**Location**: spec.md:51-61 (migration requirement, "preserving the camera's `name`") — vs `onvif_sua/worker.py:872-899` (`_cam_alarms.pop(name, None)` at 898), `worker.py:819-855` (`_stop_camera` publishes `…/camera_status/fall_sensor_online = off`, retained), `worker.py:432`, `worker.py:340-352` (alarm.json write mirrors `_cam_alarms`)
**Issue**: The spec specifies migration purely as `_teardown_camera(old_ip)` + `_spawn_worker(new_info)` and requires only that `name` is preserved. `_teardown_camera` pops the camera's entry from `_cam_alarms` (keyed by **name**, worker.py:898), and `_stop_camera` publishes a retained `fall_sensor_online: off` for that name. The respawned worker re-initialises `_cam_alarms[name] = "off"` on CGI attach (worker.py:432). Nothing in the spec requires alarm-state or MQTT-availability continuity across a migration.
**Impact**: A fall alarm that is **currently active** when the IP changes is silently cleared — in memory, in the retained MQTT topic, and (on the next periodic save) in `alarm.json`. For a fall-detection service this is loss of a safety-relevant signal, not cosmetic. Home Assistant also sees the sensor go unavailable/off and back, which can re-trigger automations.
**Example**: Resident falls at 10:04; alarm active. DHCP lease renews and the 10:06 sweep resolves a new IP → teardown publishes `off`, `_cam_alarms["soggiorno"]` is popped, the Serena spoken confirmation flow is cut mid-flight, and the new worker starts from `off`. No alert is ever re-raised.

#### H2. [HIGH] Hostname entries silently disable Serena fault reporting (`_static_cameras` consumer not updated)
**Dimension**: D1 (Logical consistency)
**Location**: tasks.md:1.2 (returned dict is `{"name","hostname"}` with no `ip`) — vs `onvif_sua/worker.py:1039-1041` (`for cam_cfg in list(config._static_cameras): ip = cam_cfg.get("ip"); if not ip: continue`), `worker.py:1113`
**Issue**: `config._static_cameras` has exactly one consumer besides startup: `_serena_fault_tick()`, which iterates it and **`continue`s on any entry without an `ip`** — its whole purpose is to flag "ALL configured cameras (not only connected ones), so a camera that never comes up is still flagged". Task 1.2 defines hostname entries as carrying no `ip`, and no task updates this consumer or the `_static_cameras` shape contract (`config.py:487` comment `[{"ip":..., "name":...}]`).
**Impact**: Hostname-configured cameras are silently excluded from the Serena fault driver — the single mechanism that announces "sensore uomo a terra … non attivo" for a camera that never comes up. Exactly the cameras most likely to fail to come up (unresolved hostname) are the ones that lose the announcement. Silent regression, no test would catch it (no existing test covers `_serena_fault_tick` over hostname entries).

#### H3. [HIGH] The auth-failure quarantine makes a hostname permanently unresolvable and pollutes `/api/status`
**Dimension**: D2 (Edge cases), D3
**Location**: spec.md:67-77 (failed-resolution requirement), tasks.md:4.5 — vs `onvif_sua/scan.py:44` (`if _is_auth_failed(ip): return None`), `scan.py:85-95` (`_mark_auth_failed(ip, "scan", …)`), `onvif_sua/state.py:100-120`
**Issue**: `_probe_ip()` returns `None` immediately for any quarantined IP and quarantines any IP that answers ONVIF but rejects every credential. `_mark_auth_failed` additionally flips the live camera row to `status="auth_failed"` (state.py:114-116) and the entry surfaces in `GET /api/status` `auth_failures`. Quarantine is sticky until restart (only `_reset_scan_auth_failures()`, called by the *manual* rescan, clears scan-sourced entries). The spec's failure model is only "no match found → keep last IP"; it never distinguishes "not on the subnet" from "quarantined, so structurally unprobeable".
**Impact**: (1) A camera whose credential was momentarily wrong gets quarantined once and can then **never** be resolved by hostname for the life of the process — the retry loop in spec.md:75-77 spins forever against a hard `return None`. (2) Every unrelated ONVIF device on the LAN accumulates a spurious `auth_failed` entry in the operator dashboard, every 10 minutes. Neither is covered by a requirement.

#### H4. [HIGH] No mutual exclusion between the resolution sweep and the manual GUI scan
**Dimension**: D3 (Performance/Safety), D2 (Concurrency)
**Location**: spec.md:79-86 (only requires `scan_active` not be touched), design.md:48 — vs `onvif_sua/scan.py:115-117` (`_scan_active`, local `sem = asyncio.Semaphore(config.SCAN_CONCUR)`), `scan.py:26` (`_scan_cancel` module-level `threading.Event`)
**Issue**: The spec's only concurrency requirement is negative ("SHALL NOT set or clear `scan_active`"). The semaphore is created **per invocation** (`scan.py:117`), so two overlapping sweeps run at `2 × SCAN_CONCUR` = 96 concurrent probes with independent credential loops. `_scan_cancel` is a single shared module-level Event: the spec does not say whether the resolution sweep observes it (operator's stop button silently aborts resolution) or ignores it (stop button appears not to work because probing continues). Neither behaviour is specified.
**Impact**: Doubled auth traffic against every host — compounding C1's lockout risk at the worst moment (the operator is actively troubleshooting). Undefined stop-button semantics. On the Snapdragon 801 board, 96 concurrent TCP+ONVIF probes also contend with the CGI attach threads and the audio pipeline.

#### H5. [HIGH] Resolved IP may collide with an already-registered runtime IP, corrupting the worker registry
**Dimension**: D2 (Edge cases)
**Location**: spec.md:39-45 (resolved IP "used as the runtime key… exactly as a static IP"), design.md:33-34,47, tasks.md:4.4 — vs `onvif_sua/worker.py:856-860` (`_worker_tasks[ip] = asyncio.create_task(...)`, no existence check), `onvif_sua/scan.py:169-177`
**Issue**: `_spawn_worker` unconditionally overwrites `_worker_tasks[ip]` — the previous task is dropped from the registry but **not cancelled**. The manual GUI scan can discover the hostname camera at its IP and spawn a non-static worker for it (`scan.py:169-177` only skips when the IP is already in `_cameras`, which it is *not* before the first resolution completes). The spec's uniqueness requirement (spec.md:5) is parse-time only and cannot see resolved IPs; design.md:47 mentions collisions between two hostname entries but not between a resolved IP and an existing runtime camera.
**Impact**: Two live workers on the same IP: orphaned, uncancellable task, duplicate ONVIF PullPoint subscriptions (the camera has a finite slot count), duplicate rule-check auth traffic, and a `_cameras[ip]` row written by two owners. `_teardown_camera` can only ever clean up one of them, so the leak survives every subsequent removal.

### Medium (Could Cause Issues)

#### M1. [MEDIUM] The ONVIF/CGI port for a hostname-resolved camera is unspecified
**Dimension**: D4 (Ambiguity)
**Location**: spec.md:43-45, tasks.md:2.1/4.4 — vs `onvif_sua/scan.py:46-53` (`open_port` from `ONVIF_PORTS = [80, 8080, 8899]`), `onvif_sua/worker.py:1130-1139` (static spawn uses `cred["port"]`), `onvif_sua/worker.py:398-402` (CGI URL reuses the same port)
**Issue**: The probe discovers an `open_port` per host; the static spawn path uses `cameras.credentials.port`. Task 4.4 says only "`_spawn_worker(new_info)` with the new IP and the preserved `name`" — the port's provenance is undefined, and the same value drives both the ONVIF connection (`connect.py:155`) and the Dahua CGI attach URL.
**Impact**: A camera answering ONVIF on 8080 either fails to connect (config port used) or gets a CGI URL on the wrong port (probe port used). Silent per-camera breakage depending on which reading the implementer picks.

#### M2. [MEDIUM] No behaviour defined for an invalid, absent, or wrong `scan.subnet`
**Dimension**: D2, D4
**Location**: spec.md:23-25, design.md:20 — vs `onvif_sua/scan.py:118-123` (invalid CIDR → log + silent `return`), `onvif_sua/config.py:23,31` (`SCAN_SUBNET` documented "kept ONLY for the manual scan"; env default `192.168.110.0/24` vs `settings.yaml` `192.168.1.0/24`)
**Issue**: The design promotes a manual-scan-only, historically-unvalidated setting to a load-bearing dependency of camera startup, with no requirement for the failure paths: invalid CIDR, missing `scan:` block, or cameras living outside the configured subnet. `_subnet_scan_once` currently returns silently on `ValueError`.
**Impact**: A stale or wrong `scan.subnet` makes every hostname camera permanently unresolvable with no distinguishing diagnostic — indistinguishable from "camera offline". Given the two defaults in the repo already disagree, this is a likely first-deploy outcome.

#### M3. [MEDIUM] Task 1.3's parse-time uniqueness check on the resolved IP is unimplementable
**Dimension**: D1 (Logical consistency)
**Location**: tasks.md:1.3 ("a resolved/declared IP cannot collide with another entry"), design.md:31 ("Uniqueness is enforced across the resolved/declared address space"), design.md:47 — vs spec.md:5 (parser-level requirement) and `onvif_sua/config.py:530-572`
**Issue**: `_load_static_cameras()` runs at boot **before** any resolution exists; a hostname entry has no IP to compare. The design assigns collision handling to two different layers in two places (parser at design.md:31, resolver at design.md:47) and the spec's Requirement 1 gives the parser rules it cannot enforce.
**Impact**: The implementer either writes a dead check or scatters half-checks across parser and resolver. Task 6.1's "uniqueness enforced" test will be written against whichever guess was made.

#### M4. [MEDIUM] Two devices reporting the same ONVIF hostname → nondeterministic winner
**Dimension**: D2 (Edge cases)
**Location**: spec.md:23-37, design.md:47 (covers only "two *entries* resolve to the same IP")
**Issue**: The reverse case — one configured `hostname`, two responding devices reporting it (a cloned/factory-default hostname, or a stale device still answering during a lease handover) — is unspecified. `_subnet_scan_once` uses `asyncio.gather`, so ordering is host-order-dependent but the resolver's dict-build order is not specified.
**Impact**: The worker attaches to an arbitrary one of the two, and may flap between them across ticks (each flap costing a full teardown/respawn, i.e. H1's alarm loss). Given `SetHostname` collisions from C2, duplicate hostnames are a realistic state.

#### M5. [MEDIUM] Credential source for a hostname-resolved camera is unspecified
**Dimension**: D4 (Ambiguity)
**Location**: spec.md:39-45, tasks.md:2.2/4.4 — vs `onvif_sua/scan.py:79` (probe returns `{user, pass}` from `_get_cred_fallbacks()`), `onvif_sua/worker.py:1131-1138` (static spawn uses `cred["user"]/cred["pass"]` from `.env`)
**Issue**: The probe returns whichever fallback credential authenticated; static cameras use the single env-sourced common credential. Task 4.4 does not say which populates `new_info`.
**Impact**: If the probe's credential is used, a hostname camera can end up running on a non-common credential (breaking the "single common credential" model and the `.env`-based recovery story); if the common credential is used, a camera that only authenticated via a fallback resolves but then fails every ONVIF/CGI call and gets quarantined.

### Low (Minor Improvements)

#### L1. [LOW] The documented rollback path depends on a log line no requirement mandates
**Dimension**: D4
**Location**: design.md:56 ("Rollback: revert the entry to `ip:` — the last-resolved IP is logged")
**Issue**: No requirement or task states that a successful resolution logs the resolved IP. Task 2.3 only mandates logging *unmatched* devices and duplicate-IP collisions.
**Impact**: The rollback procedure has no guaranteed source for the IP to revert to; the operator has to re-scan manually.

#### L2. [LOW] "Approximately every 10 minutes" leaves drift/jitter behaviour undefined
**Dimension**: D4
**Location**: spec.md:63-65, tasks.md:4.2 (`await asyncio.sleep(600)`)
**Issue**: `sleep(600)` after a variable-length sweep means the effective period is `600 s + sweep duration` and drifts; with multiple boards on one LAN, sweeps have no jitter and can synchronise. The spec's "approximately" is untestable as written.
**Impact**: Minor: a test asserting cadence has no target to assert against, and synchronised sweeps across boards multiply H4's load concern.

---

## Recommended Actions

### Priority 1: Before Implementation

- [ ] **RC1.** Add a requirement making the resolution sweep credential-safe and gated, mirroring the manual scan's protections. Sub-parts in descending order of what they actually buy:
  (a) **[load-bearing]** the loop SHALL abort each tick (log once, probe no host) when `config._password_placeholder_flags()["scan"]` is true — this is the path from "misconfigured `.env`" to "locked-out hardware";
  (b) the resolution probe SHALL authenticate with **only** the single common credential (`_COMMON_CRED`), never `_get_cred_fallbacks()` — the manual-scan credential (`SCAN_USER`/`SCAN_PASSWORD`) is a distinct secret and must never be tried against every host. Implement by giving the factored probe a `creds: list[tuple[str,str]]` parameter: the manual scan passes `_get_cred_fallbacks()`, the resolver passes the common credential only. Ties to RM5, and the same seam is what RH3 needs;
  (c) the resolution probe SHALL skip IPs already present in `state._cameras` unless that IP is the last-resolved IP of the hostname being resolved — a running camera's worker is already authenticated, so re-probing buys no information and can flip its row to `auth_failed` via `state.py:114-116`;
  (d) *[defense-in-depth]* the resolution probe SHALL acquire `state._auth_gate.wait_async(ip)` before authenticating. Note the gate is weaker here than elsewhere: `_reserve()` returns `0.0` for an unseen IP (`state.py:44-49`), so across a sweep of distinct IPs it imposes no delay, and 600 s between ticks is far outside its 5 s window. Residual value is spacing repeat attempts against the same IP and de-conflicting against a configured camera whose worker is mid-startup auth burst but not yet in `_cameras` (the window (c) cannot cover);
  (e) add scenarios: "placeholder password suppresses the resolution sweep", "resolution probe uses only the common credential", "already-running camera IPs are not re-probed" — all three are pure monkeypatch tests, no hardware needed.
- [ ] **RC2.** Resolve the hostname-vs-display-name conflict explicitly. Recommended: define `hostname` as the *expected* `GetHostname().Name` and add requirements that (a) `POST /api/cameras/{ip}/rename` is **rejected with 409** for a hostname-configured camera (the device hostname is its identity, not its label), OR (b) rename additionally rewrites the entry's `hostname:` in settings.yaml in the same transaction as the `name:`. Add a requirement that a hostname entry whose `hostname` equals its `name` is legal, and state which of the two the Serena/MQTT identity uses. Add scenarios for "rename of a hostname camera" and "hostname == name".
- [ ] **RC3.** Extend the persistence requirement from `_save_settings_yaml()` to the actual mutators. Add requirements that `_config_add_camera`, `_config_remove_camera`, `_config_name_conflict` and `_name_voice_collision` SHALL locate a hostname entry by its **runtime-resolved IP → hostname** reverse mapping (from the `state.py` cache) and SHALL update/remove that existing entry in place, never appending an `ip:` entry for it. Add scenarios: "rename of a resolved hostname camera leaves exactly one entry, still keyed by `hostname`", "remove of a resolved hostname camera deletes the `hostname` entry and returns removed=True", "`_name_voice_collision` does not report a hostname entry as colliding with itself" (today `str(e.get("ip"))` yields `"None"`, producing the bogus error *"il nome … coincide con la telecamera None"*). Add tasks under §1 for all four helpers and under §6 for the three scenarios.

### Priority 2: Should Address

- [ ] **RH1.** Add a migration-continuity requirement: before `_teardown_camera(old_ip)`, snapshot `_cam_alarms[name]` and the camera's Serena fault-episode fields; after `_spawn_worker(new_info)` succeeds, restore them, and suppress the retained `fall_sensor_online: off` publish when the teardown is a migration (e.g. `_stop_camera(ip, publish_offline=False)`). Add scenarios: "migration with an active alarm preserves the alarm state and does not publish fall_sensor_online off", "migration does not re-trigger the Serena ready announcement".
- [ ] **RH2.** Add a requirement that `config._static_cameras` entries for hostname cameras carry the currently-resolved IP (or that `_serena_fault_tick` resolves hostname→IP via the state cache), so every configured camera — resolved or not — is still evaluated by the Serena fault driver. Update tasks.md:1.2 to state the new dict contract explicitly (`{"name", "ip"|None, "hostname"|None}`) and add a task to update `worker.py:1039-1041`. Add a scenario: "an unresolved hostname camera is still announced as faulty by the Serena fault driver".
- [ ] **RH3.** Add a requirement that the resolution probe SHALL ignore the `_auth_failed` quarantine for read-only identity probing *or* that a quarantined IP is reported as a distinct `resolution_blocked` diagnostic rather than a silent no-match, and that the resolution sweep SHALL NOT call `_mark_auth_failed` (it must never quarantine third-party devices or flip a live camera row to `auth_failed`). Add scenarios: "quarantined IP does not silently block resolution forever", "resolution sweep adds no entries to /api/status auth_failures".
- [ ] **RH4.** Add a mutual-exclusion requirement: a single module-level `asyncio.Lock` (or shared semaphore) SHALL serialise the manual sweep and the resolution sweep, so at most `SCAN_CONCUR` probes are in flight process-wide; when a manual scan is running, the resolution tick SHALL skip (log) and retry on the next tick. Specify explicitly that the resolution sweep does **not** observe `_scan_cancel`. Add scenarios: "resolution tick skips while a manual scan is active", "operator stop-scan does not abort resolution".
- [ ] **RH5.** Add a requirement that `_spawn_worker` SHALL be a no-op (log a collision) when `ip` is already in `state._worker_tasks`/`state._cameras` and not owned by the requesting hostname, and that a hostname resolving to an IP already owned by a static entry or a manual-scan camera is rejected with a diagnostic (keep the incumbent). Add scenarios: "resolved IP already owned by a static entry is rejected", "resolved IP already discovered by a manual scan does not spawn a second worker".

### Priority 3: Could Improve

- [ ] **RM1.** State that a hostname camera's port comes from `cameras.credentials.port` (same as static entries) and that the probe's discovered `open_port` is used only to satisfy the ONVIF reachability check — or, if the discovered port wins, that it is carried into both the ONVIF connect and the Dahua CGI URL. Add a scenario pinning the chosen rule.
- [ ] **RM2.** Add a requirement for subnet failure paths: an invalid/absent `scan.subnet` SHALL log a distinct error naming the setting once per tick (not the current silent `return`), and hostname cameras SHALL be reported as "unresolvable: subnet not configured" rather than "not found". Also document in `serena_sua_config.md` that `scan.subnet` is no longer manual-scan-only and must contain the cameras (§5.2).
- [ ] **RM3.** Move all IP-collision enforcement to the resolver and restate spec.md:5's parser rule as *hostname* uniqueness + `ip` uniqueness only (no cross-space check). Rewrite tasks.md:1.3 to "hostnames unique (case-insensitive) among entries; `ip` unique among entries" and add a resolver-level task for "resolved IP already claimed → keep first, log".
- [ ] **RM4.** Add a requirement that when more than one responding device reports a wanted hostname, the resolver SHALL log all candidates, prefer the currently-running IP if it is among them (avoiding a needless migration), and otherwise pick the lowest IP deterministically. Add a scenario.
- [ ] **RM5.** State that a hostname-resolved camera SHALL run on the common env-sourced credential (`_COMMON_CRED`), identical to static entries, and that a device matching by hostname but rejecting the common credential is *not* resolved (logged as a credential mismatch). Follows from RC1(b).

### Priority 4: Nice to Have

- [ ] **RL1.** Add a requirement that each successful resolution logs `hostname → ip` at INFO on first resolution and on every change (not on unchanged ticks, to avoid a log line every 10 minutes), so design.md:56's rollback procedure has a guaranteed source.
- [ ] **RL2.** Replace "approximately every 10 minutes" with a testable statement: "the next sweep starts 600 s after the previous sweep **completes**, ± up to 30 s of random jitter", and make the interval a module constant so tests can monkeypatch it.

---

## FTR Calculation

Starting at 100%:
- 3 Critical: -45%
- 5 High: -40%
- 5 Medium: -15%
- 2 Low: -2%
= **-2% → floored to 30%**

The floor is doing real work here: any one of C1–C3 alone is enough to make the first implementation wrong in production. C1 in particular can damage the hardware it is meant to keep online.

---

## Assessment

The spec's *structure* is good — requirements are atomic, scenarios are in Given/When/Then form and cover the state machine (resolve / no-change / change / fail / never-resolved), the design records real trade-offs, and the tasks are concrete with line references. The failure is one of **integration analysis**: the change treats `scan.py` as a neutral utility (it is a deliberately-quarantined, safety-gated subsystem), treats the ONVIF hostname as immutable (the service itself mutates it), and treats "never persisted" as a property of the YAML writer (it is a property of the IP-keyed mutators the GUI calls). Recommend addressing RC1–RC3 and RH1–RH5 before writing code; the remaining items can be folded in during implementation.
