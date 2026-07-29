# hostname-camera-resolution Specification

## Purpose

Let a camera be configured by its ONVIF device hostname instead of a static IP, so a DHCP
lease change cannot silently break its ONVIF connection and CGI stream. Covers resolving the
hostname to a current address by subnet scan, caching that address at runtime without ever
persisting it, re-resolving periodically and on every scan, migrating the running worker when
the address changes, and refusing to guess when the hostname is ambiguous — while leaving
static-`ip` configuration behaviour unchanged.

## Requirements

### Requirement: A camera may be configured by ONVIF hostname instead of a static IP

Each entry in the `settings.yaml` `cameras.list` SHALL require a `name` and SHALL supply exactly one address key: either `ip` (a static address, behaving exactly as before) or `hostname` (the camera's ONVIF device hostname). An entry that supplies neither, or both, SHALL be rejected and ignored, with a diagnostic logged. Static-`ip` entries SHALL be parsed and behave byte-for-byte as they do today. The `hostname` value SHALL NOT be treated as an IP address and SHALL be carried through configuration parsing so it can be resolved at runtime.

#### Scenario: Hostname entry is accepted
- **WHEN** a `cameras.list` entry has `name` and `hostname` but no `ip`
- **THEN** the entry is loaded as a hostname-configured camera and retained for runtime resolution

#### Scenario: Static IP entry is unchanged
- **WHEN** a `cameras.list` entry has `name` and `ip` but no `hostname`
- **THEN** the entry is loaded and behaves exactly as before this change (no resolution step)

#### Scenario: Entry with neither ip nor hostname is rejected
- **WHEN** a `cameras.list` entry supplies neither `ip` nor `hostname`
- **THEN** the entry is ignored and a diagnostic is logged

#### Scenario: Entry with both ip and hostname is rejected
- **WHEN** a `cameras.list` entry supplies both `ip` and `hostname`
- **THEN** the entry is ignored and a diagnostic is logged

### Requirement: `name` is the camera's identity, `hostname` is only its discovery key

`name` SHALL remain the sole identity used for MQTT topics, Home Assistant discovery, persisted alarm state, and the Serena voice phrase — a hostname-configured camera is indistinguishable from a static-`ip` one on those interfaces. `hostname` SHALL be used only to resolve the camera's current IP.

The two values are independent and SHALL both be accepted whether they differ or coincide: an operator may pair a factory device hostname with a friendly room name (`hostname: STANZA_11`, `name: soggiorno`), or use the same string for both. Neither case is a configuration error.

#### Scenario: Hostname differing from name is accepted
- **WHEN** a `cameras.list` entry declares a `hostname` that differs from its `name`
- **THEN** the entry is loaded and both values are retained

#### Scenario: Hostname equal to name is accepted
- **WHEN** a `cameras.list` entry declares a `hostname` equal to its `name`
- **THEN** the entry is loaded and no duplicate/collision diagnostic is emitted for that entry

#### Scenario: MQTT and Serena identity come from name, not hostname
- **WHEN** a hostname-configured camera whose `hostname` differs from its `name` is running
- **THEN** its MQTT topics, Home Assistant discovery and Serena phrase use `name`, exactly as for a static-`ip` camera, and `hostname` appears in none of them

### Requirement: Hostnames are resolved to a current IP at boot by scanning the subnet

At startup, for every hostname-configured camera the service SHALL resolve the hostname to a current IP by scanning the configured `scan.subnet`, probing each responding ONVIF device, and matching the device's reported ONVIF hostname (`GetHostname().Name`, trimmed, case-insensitive) against the configured `hostname`. A camera worker for a hostname entry SHALL only be spawned once its hostname has resolved to an IP. The resolution SHALL run one subnet sweep for all pending hostnames rather than one sweep per camera.

Static-`ip` cameras SHALL be spawned immediately at startup from the address in the file, with no discovery step, exactly as before this change. Hostname-configured cameras SHALL be deferred to the resolution task instead, whose first sweep runs immediately rather than after a full interval.

Because the resolved IP is never persisted (see the runtime-cache requirement), the service SHALL start each run with no knowledge of any hostname camera's address and SHALL rediscover it by sweeping. A hostname camera therefore has no worker until the first sweep completes, which on a `/24` subnet is a matter of seconds, not instant.

#### Scenario: Hostname resolves and worker starts
- **WHEN** the service boots and a responding device on the subnet reports an ONVIF hostname equal (case-insensitive) to a configured `hostname`
- **THEN** that device's IP is used and a camera worker is spawned on that IP

#### Scenario: Match is case-insensitive and trimmed
- **WHEN** the configured `hostname` differs from the device-reported hostname only by letter case or surrounding whitespace
- **THEN** the two are considered a match

#### Scenario: One sweep resolves multiple hostnames
- **WHEN** several cameras are configured by hostname
- **THEN** a single subnet sweep resolves all of them, not one sweep per camera

#### Scenario: Static-IP cameras do not wait for the sweep
- **WHEN** the service boots with both a static-`ip` entry and a `hostname` entry
- **THEN** the static-`ip` camera's worker is started straight away from the configured address, while the hostname camera's worker waits for the first sweep

#### Scenario: No address is remembered from the previous run
- **WHEN** the service is restarted while a hostname camera was resolved and running
- **THEN** the runtime cache starts empty and the camera's address is rediscovered by the boot sweep — the previous run's IP is not reused

#### Scenario: A hostname that does not answer at boot is retried, not failed
- **WHEN** a hostname-configured camera is offline during the boot sweep
- **THEN** no worker is spawned for it, this is not an error state, and it is retried on every subsequent resolution

### Requirement: An ambiguous hostname is never resolved to an arbitrary device

More than one responding device can report the same ONVIF hostname — most commonly identical cameras still carrying a factory-default hostname, or a device that was renamed to a name a configured entry also uses. The resolver SHALL detect this and SHALL NOT attach to an arbitrary candidate:

- When a worker is already running for that hostname, the service SHALL keep that worker on its current IP and SHALL NOT migrate — whether or not the running IP is among the candidates. An ambiguous scan is treated as "no change", exactly like a failed resolution.
- When no worker is running for that hostname, the service SHALL NOT resolve it and SHALL NOT spawn a worker. The hostname stays unresolved and is retried on every subsequent scan, so an operator who gives the devices distinct hostnames recovers without restarting the service.
- The service SHALL log every candidate IP for the ambiguous hostname. Because the scan repeats every 10 minutes, this diagnostic SHALL be emitted when the ambiguity first appears and whenever the candidate set changes — not on every scan.

Attaching to an arbitrary candidate is specifically excluded rather than merely undesirable. `name` is the room identity carried by every alarm, MQTT topic, Home Assistant entity and Serena announcement, so a wrong pick would monitor one room while reporting another room's name — and would announce that room's sensor as active. An unresolved camera fails **loudly** (no worker, surfaced by the Serena fault driver and the dashboard); a misattributed camera fails **silently**, and sends help to the wrong room.

Where the collision runs the other way — two *configured* hostnames resolving to the same IP — the entry that keeps the IP SHALL be the one appearing first in `cameras.list`, so the outcome does not depend on scan completion order.

#### Scenario: Two devices reporting a wanted hostname resolve to neither
- **WHEN** a scan finds two responding devices that both report a configured `hostname`, and no worker is running for that hostname
- **THEN** no IP is resolved, no worker is spawned, and both candidate IPs are logged

#### Scenario: Ambiguity does not disturb a running worker
- **WHEN** a scan finds two devices reporting the `hostname` of a camera whose worker is already running
- **THEN** the worker keeps running on its current IP, no teardown or respawn occurs, and the ambiguity is logged

#### Scenario: Ambiguity clears without a restart
- **WHEN** one of two devices sharing a hostname is given a different hostname, and the next periodic scan runs
- **THEN** the configured hostname resolves to the single remaining candidate and its worker is spawned

#### Scenario: The ambiguity diagnostic is not repeated every scan
- **WHEN** the same ambiguous candidate set is seen on consecutive scans
- **THEN** the diagnostic is logged on the first scan and not repeated until the candidate set changes

#### Scenario: Two configured hostnames resolving to one IP are broken deterministically
- **WHEN** two hostname entries both resolve to the same IP
- **THEN** the entry appearing first in `cameras.list` keeps it, the other is left unresolved with a diagnostic, and the outcome is the same regardless of the order in which probes completed

### Requirement: The resolved IP is cached at runtime and never persisted to settings.yaml

The service SHALL cache each configured hostname's last-resolved IP in runtime state (guarded by the existing runtime lock) and SHALL use it as the runtime key for the camera exactly as a static IP is used. The resolved IP SHALL NOT be written back into `settings.yaml`; the `hostname` SHALL remain the authoritative value in the configuration file, including across configuration saves.

#### Scenario: Resolved IP drives the runtime worker
- **WHEN** a hostname has resolved to an IP
- **THEN** the ONVIF connection and Dahua CGI stream for that camera use the resolved IP, and runtime structures are keyed by that IP

#### Scenario: Saving configuration does not persist the resolved IP
- **WHEN** the service saves `settings.yaml` while a hostname camera is resolved to an IP
- **THEN** the saved file still contains `hostname` for that entry and does not contain a resolved `ip` for it

#### Scenario: The cache does not outlive the process
- **WHEN** the service stops
- **THEN** no resolved IP is written to disk anywhere, and the next run begins with an empty cache

### Requirement: Configuration helpers identify a hostname entry by its resolved IP

Every web API path addresses a camera by its runtime IP. For a hostname-configured camera that is the *resolved* IP, and its `cameras.list` entry has no `ip` key at all. Every configuration helper that locates or compares an entry by IP SHALL therefore first map the runtime IP back to the configured hostname via the runtime cache, and match the entry by that hostname.

No helper SHALL compare a runtime IP against the rendered text of an absent `ip` key. Rendering a missing key yields the literal string `"None"`, which never equals a real IP — so a hostname entry is silently classified as "a different camera" by every such comparison, and any diagnostic built from it names the camera `None`. A hostname entry SHALL never be reported as conflicting with itself, and a diagnostic that names a conflicting hostname-configured camera SHALL name it by its `hostname` (or `name`), never `None`.

#### Scenario: A hostname entry is not mistaken for a different camera
- **WHEN** a helper checks whether a name or normalised voice name is already used, and the only entry holding it is the resolved hostname entry of the camera being checked
- **THEN** no conflict is reported

#### Scenario: A hostname camera can be renamed to a name that normalises like its current one
- **WHEN** a resolved hostname camera named `sala_pranzo` is renamed to `sala pranzo` (or to a case variant of its current name), so the normalised Serena voice name is unchanged
- **THEN** the rename is accepted rather than rejected as a voice-name collision with itself

#### Scenario: A genuine conflict names the other camera usefully
- **WHEN** a rename or save is rejected because another **hostname-configured** entry already holds that name or normalised voice name
- **THEN** the diagnostic identifies that entry by its `hostname` or `name`, and never by the literal `None`

#### Scenario: Static-IP entries are matched exactly as before
- **WHEN** a helper locates a static-`ip` entry
- **THEN** it matches on `ip` with behavior unchanged by this change

### Requirement: Renaming a hostname-configured camera rewrites its configured hostname

Renaming a camera sets the camera's **ONVIF device hostname** on the device (`SetHostname`) — the very value the resolution scan matches on. For a hostname-configured camera the service SHALL therefore rewrite that entry's `hostname` alongside its `name`, in the single `settings.yaml` save that persists the rename, so the entry still resolves afterwards. A rename SHALL NOT leave the entry's `hostname` pointing at a value the device no longer reports.

The value written SHALL be the hostname the device **actually reports** on the post-rename verification read, not the requested name — so a device that normalises or truncates the requested name still leaves a resolvable entry. When the verification read fails, the requested name SHALL be written and the unverified rewrite SHALL be logged as a warning naming both the old and the new hostname.

The rewritten entry SHALL continue to carry `hostname` and SHALL NOT gain an `ip` key. Renaming a static-`ip` camera SHALL behave exactly as before this change and SHALL NOT add a `hostname` key to its entry.

#### Scenario: Rename rewrites hostname and name together
- **WHEN** a resolved hostname-configured camera is renamed and the device confirms the new hostname
- **THEN** that entry's `hostname` and `name` are both the new value after a single save, the entry still has no `ip` key, and the entry still resolves on the next scan

#### Scenario: Rename updates the existing entry rather than appending a second one
- **WHEN** a resolved hostname-configured camera is renamed
- **THEN** `cameras.list` still holds exactly one entry for that camera — the rename SHALL NOT append a new `{ip, name}` entry alongside the existing `hostname` entry (which would produce two entries for one physical camera and, on the next load, a duplicate-name rejection that drops both)

#### Scenario: Device reports a hostname different from the requested name
- **WHEN** the post-rename verification read reports a hostname that differs from the requested name
- **THEN** the reported value is written as the entry's `hostname` (so the entry matches what the device will report), the requested name is still written as `name`, and the divergence is logged

#### Scenario: Verification read fails after the device accepted the rename
- **WHEN** `SetHostname` succeeds but the verification read of the device hostname fails
- **THEN** the requested name is written as the entry's `hostname` and a warning naming both the previous and the new hostname is logged

#### Scenario: Persisting the rename fails after the device was changed
- **WHEN** the device hostname has been changed but the `settings.yaml` save fails
- **THEN** the rename is reported as failed and the device's new hostname is logged at warning level so the operator can repair the entry by hand

#### Scenario: Renaming a static-IP camera is unchanged
- **WHEN** a static-`ip` camera is renamed
- **THEN** only its `name` changes, its entry keeps `ip` and gains no `hostname` key

#### Scenario: An unresolved hostname camera cannot be renamed
- **WHEN** a rename targets a hostname-configured camera that has never resolved, so no worker and no runtime camera row exist for it
- **THEN** the request fails with a camera-not-found error and neither the device nor `settings.yaml` is modified

### Requirement: A rename that would hijack another entry's hostname is rejected

Because renaming sets the device hostname, a rename can make one camera answer to a hostname another entry resolves by. Before the device is touched, the service SHALL reject the rename with a diagnostic when the requested name equals the configured `hostname` of any **other** camera entry, compared trimmed and case-insensitively — the same comparison the resolution match uses. This check SHALL apply whether the camera being renamed is hostname- or static-`ip`-configured. A requested name equal to the renamed camera's **own** configured `hostname` SHALL be allowed.

#### Scenario: Rename colliding with another entry's hostname is rejected
- **WHEN** an operator renames a camera to a name equal (trimmed, case-insensitive) to another entry's configured `hostname`
- **THEN** the rename is rejected before `SetHostname` is called, the device hostname is unchanged, and `settings.yaml` is unchanged

#### Scenario: Rename to the camera's own hostname is allowed
- **WHEN** the requested name equals the renamed camera's own configured `hostname`
- **THEN** the rename proceeds

### Requirement: A rename re-keys the runtime hostname cache without disturbing the worker

When a rename rewrites a hostname entry's `hostname`, the service SHALL move that hostname's cached last-resolved IP to the new hostname key under the existing runtime lock, and SHALL leave no entry under the old hostname. The rename SHALL NOT tear down or respawn the camera's worker: the IP has not changed, only the key it is cached under.

#### Scenario: The cache follows the rename
- **WHEN** a resolved hostname camera is renamed
- **THEN** the runtime cache maps the new hostname to the previously resolved IP and holds no entry for the old hostname

#### Scenario: The first scan after a rename spawns no duplicate worker
- **WHEN** the first periodic re-resolution runs after a rename
- **THEN** the device's new hostname matches the rewritten configured `hostname`, the resolved IP equals the running worker's IP, and no teardown, respawn, or second worker occurs

#### Scenario: A rename does not interrupt the camera
- **WHEN** a resolved hostname camera is renamed
- **THEN** its worker keeps running on the same IP and its alarm state is preserved

### Requirement: Removing a resolved hostname camera deletes its configuration entry

Removing a camera by its runtime IP SHALL delete the `cameras.list` entry of a hostname-configured camera identified by its resolved IP, SHALL report the removal as performed, and SHALL drop that hostname's cached resolved IP from runtime state.

A removal that tears down the worker but leaves the entry in place is not sufficient: the entry is what drives resolution, so the periodic scan would find the hostname unresolved-with-no-worker and **respawn the camera within one interval** — the camera would come back by itself, without a restart.

#### Scenario: Removal deletes the hostname entry
- **WHEN** a resolved hostname-configured camera is removed
- **THEN** its `cameras.list` entry is gone from `settings.yaml`, the removal is reported as performed, and its cached resolved IP is dropped from runtime state

#### Scenario: A removed hostname camera does not come back
- **WHEN** the next periodic resolution scan runs after a hostname camera has been removed
- **THEN** no worker is spawned for that hostname, even though its device is still online and still reports that hostname

#### Scenario: Removing a static-IP camera is unchanged
- **WHEN** a static-`ip` camera is removed
- **THEN** its entry is removed by `ip` exactly as before this change

### Requirement: Hostnames are re-resolved every 10 minutes and the worker migrates on IP change

The service SHALL re-run the hostname resolution scan on a periodic background task every 10 minutes (600 seconds). When a hostname resolves to an IP that differs from the IP its worker is currently running on, the service SHALL migrate the worker by tearing down the worker on the old IP and spawning a new worker on the new IP, preserving the camera's `name`. When the resolved IP is unchanged, the service SHALL take no action for that camera.

#### Scenario: IP change migrates the worker
- **WHEN** a periodic re-resolution finds a hostname now maps to a different IP than the running worker
- **THEN** the worker on the old IP is torn down and a new worker is spawned on the new IP under the same camera name

#### Scenario: Unchanged IP is a no-op
- **WHEN** a periodic re-resolution finds the same IP the worker is already running on
- **THEN** no teardown or respawn occurs for that camera

#### Scenario: Re-resolution runs on a 10-minute cadence
- **WHEN** the service has been running
- **THEN** the hostname resolution scan repeats approximately every 10 minutes for the lifetime of the process

### Requirement: A subnet scan reconciles a hostname camera instead of duplicating it

A subnet scan probes the same devices as the resolution sweep and already reads each one's ONVIF hostname. A responding device whose reported hostname matches a configured `cameras.list` entry SHALL therefore be treated as **that camera** — possibly at a new address — and SHALL NOT be adopted as a newly discovered camera. When its address differs from the one the camera's worker is running on, the scan SHALL migrate the worker exactly as a periodic re-resolution does. This applies to every scan, operator-triggered or periodic.

Without this, a scan that runs before the next re-resolution spawns a *second*, non-persistent worker for a camera that already has one: the dashboard shows the same physical camera twice — once on the stale address, failing and retrying, and once on the new one. It also means an address change is picked up at scan cadence rather than only on the resolution interval.

A device reporting a configured `hostname` SHALL NOT be adopted as a discovered camera **even when that hostname is ambiguous**. Excluding only successfully-resolved devices would let the ambiguity case reach the discovery path and start workers for both twins under the name the ambiguity rule exists to protect — reintroducing the misattribution it refuses.

#### Scenario: A scan finds a configured hostname camera at a new address
- **WHEN** a scan finds a device reporting the `hostname` of a configured entry, at an address different from the one its worker is running on
- **THEN** the worker on the old address is torn down and a new one is spawned on the new address under the same `name`, the runtime cache follows, and exactly one dashboard row exists for that camera

#### Scenario: A scan finds a configured hostname camera at its current address
- **WHEN** a scan finds the camera at the address its worker is already running on
- **THEN** no teardown, respawn, or second row occurs

#### Scenario: A scan still discovers unconfigured devices
- **WHEN** a scan finds both a configured hostname camera and a device matching no configured entry
- **THEN** only the unconfigured device is added as a discovered camera

#### Scenario: An ambiguous hostname is not adopted by discovery
- **WHEN** a scan finds two devices both reporting a configured `hostname`
- **THEN** neither is adopted as a discovered camera, no migration occurs, and any running worker keeps its current address

#### Scenario: A stale row is cleared even without a live worker
- **WHEN** a hostname camera's worker has already died on its old address and a scan finds the device at a new one
- **THEN** the stale entry is torn down so the camera does not remain as a second dashboard row

### Requirement: Saving a discovered camera records its ONVIF hostname

Persisting a scan-discovered camera SHALL create a `{hostname, name}` entry using the ONVIF hostname the device reported during discovery, so that a later address change is followed automatically instead of orphaning a pinned `ip`. When the device reports no usable ONVIF hostname, the entry SHALL fall back to `{ip, name}` and the fallback SHALL be logged, since that entry will need manual editing if the address changes.

Saving SHALL NOT write to the device: it records the hostname the camera already reports. Assigning a different hostname is the rename operation.

Saving SHALL be refused, with a diagnostic naming the other camera, when the reported hostname is already used by another entry. Two entries sharing a hostname are both rejected as a configuration error at the next load, so accepting the save would silently take two working cameras offline at the next restart; factory-default hostnames are identical across cameras of a model, making this the common case rather than an edge one.

A camera that ALREADY has an entry SHALL keep that entry's address form: saving SHALL update its `name` without converting an `ip` entry to `hostname` or the reverse, and SHALL NOT append a second entry. A successful save SHALL make the camera visible to the resolution loop and record its current address in the runtime cache, so it is tracked without a restart.

#### Scenario: A discovered camera is saved by hostname
- **WHEN** a scan-discovered camera reporting an ONVIF hostname is saved with a name
- **THEN** `cameras.list` gains a `{hostname, name}` entry carrying the reported hostname, with no `ip` key

#### Scenario: A device with no ONVIF hostname falls back to a static entry
- **WHEN** a discovered camera reporting no ONVIF hostname is saved
- **THEN** an `{ip, name}` entry is written and the fallback is logged

#### Scenario: A saved hostname camera follows a later address change
- **WHEN** a camera saved by hostname later answers at a different address
- **THEN** the next resolution or scan migrates its worker to the new address without any edit to `settings.yaml`

#### Scenario: A save colliding with another entry's hostname is refused
- **WHEN** the reported hostname of the camera being saved equals another entry's configured `hostname`
- **THEN** the save is refused with a diagnostic naming that other camera, and no entry is appended

#### Scenario: An existing entry keeps its address form
- **WHEN** a camera that already has a static-`ip` entry is saved
- **THEN** only its `name` is updated, the entry keeps `ip`, and no `hostname` key is added

#### Scenario: Saving an already-configured hostname camera updates it in place
- **WHEN** a camera whose entry is already hostname-configured is saved
- **THEN** that single entry's `name` is updated and no second entry is created

### Requirement: Failed resolution keeps the last known IP

When a periodic re-resolution fails to find a match for a hostname whose worker is already running, the service SHALL keep using the last-resolved IP and SHALL leave that worker running. A hostname that has never resolved SHALL have no worker and SHALL be retried on each subsequent periodic scan until it resolves. A failed resolution SHALL NOT tear down a working camera.

#### Scenario: Transient failure does not drop a running camera
- **WHEN** a re-resolution scan returns no match for a hostname whose worker is currently running
- **THEN** the worker keeps running on its last-resolved IP and no teardown occurs

#### Scenario: Never-resolved hostname is retried
- **WHEN** a hostname has not yet resolved to any IP
- **THEN** no worker is spawned for it and it is retried on the next periodic scan

### Requirement: The resolution scan does not disturb the manual-scan control state

The periodic hostname resolution scan SHALL be independent of the operator-triggered manual subnet scan. It SHALL NOT set or clear the `scan_active` flag exposed by `GET /api/status`, and it SHALL NOT interfere with the manual stop-scan control.

#### Scenario: Resolution scan leaves scan_active untouched
- **WHEN** the periodic hostname resolution scan runs while no manual scan is in progress
- **THEN** `GET /api/status` continues to report `scan_active: false`
