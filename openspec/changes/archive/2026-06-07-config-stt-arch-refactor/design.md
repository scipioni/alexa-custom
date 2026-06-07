## Context

`alexa_custom` is a headless voice assistant daemon. Its configuration currently lives in a single flat `config.yaml` at the project root, with credentials mixed into an `env:` section that injects into `os.environ`, a single optional `actions.yaml` for triggers, and one STT backend shared across wake-word detection (stage 1) and command recognition (stage 2). As the system grew to ~10 subsystems (LiveKit, Vosk, sherpa-onnx, Piper, Ollama, MQTT, Telegram, PipeWire, web dashboard, learning agent), the flat config became unmaintainable and semantically ambiguous. The refactor imposes a clean folder layout, moves credentials out, and gives each stage of the STT pipeline its own backend.

## Goals / Non-Goals

**Goals:**
- Structured `conf/` folder with logical separation: secrets, config, actions directory
- `conf/secrets.yaml` (git-ignored) holds all credentials; applied to `os.environ` at startup
- `conf/config.yaml` uses nested blocks matching subsystem boundaries
- `conf/actions/` auto-discovers `.yaml` files; `system.yaml` always first; first-match-wins
- Independent STT backends for stage 1 (wake) and stage 2 (command)
- No backward compatibility — clean break, no legacy key aliases

**Non-Goals:**
- Multi-host or networked config distribution
- Config encryption or secrets manager integration (plain file is sufficient for this deployment)
- Schema validation beyond what Python dataclasses + explicit parse functions provide
- Dynamic loading of custom STT backends beyond vosk / sherpa-onnx

## Decisions

### D1 — `conf/` folder, not config split across multiple root-level files

**Decision:** All config lives under a `conf/` directory. `config.yaml`, `secrets.yaml`, and the `actions/` sub-directory are siblings inside it.

**Rationale:** Keeps the project root clean. A single well-named directory signals "configuration lives here" without requiring documentation. Alternative of keeping files at the project root adds noise and makes gitignoring `secrets.yaml` more fragile (a root-level gitignore entry is more likely to be accidentally removed).

**Alternative considered:** Multiple root-level files (`config.yaml`, `secrets.yaml`, `actions.yaml`). Rejected: root gets crowded; gitignoring a root-level `secrets.yaml` is easy to break.

---

### D2 — `secrets.yaml` applied to `os.environ` at startup, not passed explicitly

**Decision:** `load_secrets()` reads `conf/secrets.yaml` and applies relevant keys to `os.environ` (LIVEKIT_URL, LIVEKIT_API_KEY, etc.) before any subsystem initialises. The LiveKit SDK, Telegram client, and MQTT client continue reading from env vars as before.

**Rationale:** Minimal code change — subsystems don't need new constructor arguments. Secrets behave identically to the old `env:` section, just loaded from a dedicated file. Explicit threading of a `SecretsConfig` object through every call site would be a much larger change with no benefit for this single-host deployment.

**Alternative considered:** `SecretsConfig` dataclass passed explicitly to each subsystem. Rejected: disproportionate refactor scope; all subsystem clients already have env-var reading wired into their SDKs.

---

### D3 — `conf/actions/` auto-discovery, `system.yaml` hardcoded as first

**Decision:** `_load_actions_dir()` always loads `conf/actions/system.yaml` first, then `glob("*.yaml")` sorted alphabetically excluding `system.yaml`. First-match-wins across the merged trigger list.

**Rationale:** Explicit ordering without requiring users to name files with numeric prefixes. `system.yaml` as a reserved name is self-documenting. First-match-wins means system commands cannot be accidentally overridden by user or learned files — to change a system command, edit `system.yaml` directly (intentional, as stated by the user).

**Alternative considered:** Numeric prefix convention (`00-system.yaml`, `10-user.yaml`). Rejected: requires discipline on every file addition; surprising when `99-custom.yaml` has higher priority than `system.yaml`.

**Alternative considered:** Last-match-wins so later user files override system. Rejected: would allow `learned.yaml` to accidentally shadow system commands; user explicitly agreed that system actions are the authority.

---

### D4 — `on_startup` restricted to `system.yaml` only

**Decision:** The `_load_actions_dir()` parser reads `on_startup` only from the first file (`system.yaml`). It is ignored (with a debug log) in all subsequent files.

**Rationale:** A startup announcement is a system concern, not a per-file concern. Allowing multiple files to define `on_startup` would cause multiple announcements on every restart — confusing and hard to debug. The system file is the single authority for what happens at boot.

---

### D5 — Two STT backend instances in `run_stt_worker`

**Decision:** `run_stt_worker` loads `stage1_backend` and `stage2_backend` independently at startup. `_recognition_loop` uses `stage1_backend` for continuous wake-word detection; `_wake_detected` receives `stage2_backend` and passes it to `capture_transcript`.

**Rationale:** Stage 1 runs always-on at low CPU (Vosk with grammar constraint). Stage 2 runs for only a few seconds after each wake event and benefits from higher-accuracy open-vocabulary recognition (sherpa-onnx). Both models load at startup to avoid latency on the first wake event. The existing `STTBackend` ABC is sufficient — no new interface needed.

**Memory implication:** Both models live in RAM simultaneously. On the Arduino Uno Q (Snapdragon 801, ~1 GB RAM), Vosk (Italian model ~50 MB) + sherpa-onnx kroko_128l (~120 MB) is within budget.

**Alternative considered:** Lazy-load stage2 on first wake. Rejected: first-wake latency would be perceptible; model loading can take 2–5 seconds.

---

### D6 — `stt.stage1.confidence` replaces top-level `wake_confidence`

**Decision:** The Vosk word confidence threshold moves from `recognition.confidence` to `stt.stage1.confidence` in the YAML and from `ActionsConfig.wake_confidence` to `STTStage1Config.confidence` in Python.

**Rationale:** Confidence scoring is a Vosk-specific implementation detail of stage-1 wake detection. It has no meaning for sherpa-onnx (which uses fuzzy text matching) or for stage-2 command recognition. Placing it under `stt.stage1` makes its scope clear and avoids confusion when users configure sherpa-onnx for stage 1.

---

### D7 — `ActionsConfig` retains flat structure at top level, sub-configs as nested dataclasses

**Decision:** `ActionsConfig` becomes a container with typed sub-config fields (`audio: AudioConfig`, `stt: STTConfig`, etc.) instead of 20+ flat fields. Access site changes from `config.tts_backend` to `config.tts.backend`.

**Rationale:** Sub-dataclasses mirror the YAML structure exactly, making the mapping obvious and reducing the chance of parsing bugs. Subsystems that only need one sub-config (e.g., `audio.py` only needs `AudioConfig`) can receive just that slice rather than the full god-object.

---

### D8 — Hot-reload watches directory, not individual files

**Decision:** `ConfigManager` uses `os.scandir()` on `conf/actions/` to detect mtime changes across all files, in addition to watching `conf/config.yaml`. `conf/secrets.yaml` is not watched — requires restart.

**Rationale:** Adding a new file to `conf/actions/` should take effect on the next poll without restarting the daemon. Watching a directory for any `.yaml` change is straightforward with the existing mtime-poll approach. Secrets changes are rare and security-sensitive; requiring restart for them is intentional.

## Risks / Trade-offs

- **Breaking change with no migration path** → Explicit decision per user requirement. Old `config.yaml` at project root will be ignored silently (or error if parse fails). Document clearly in README and CHANGELOG.
- **Both STT models in RAM simultaneously** → Acceptable on this board; document RAM budget in CLAUDE.md. If RAM becomes an issue, lazy-load can be added later.
- **`system.yaml` as reserved filename** → Users cannot name their own file `system.yaml`. The name is self-documenting and the restriction is worth the predictability.
- **Alphabetical ordering of user files** → Users with ordering requirements must use filename prefixes (`00-home.yaml`). Document the convention; auto-discovery is simpler than an explicit list for the common case.
- **`learned.yaml` position in alpha order** → `learned.yaml` ('l') loads before `user.yaml` ('u'). Learned commands therefore have higher priority than hand-written user commands. This is unlikely to matter in practice (learned commands are new phrases) but worth documenting.

## Migration Plan

This is a clean break — no backward compatibility. Migration steps:

1. Create `conf/` directory
2. Move credentials from `config.yaml env:` to `conf/secrets.yaml`
3. Rewrite `conf/config.yaml` using new nested-block schema
4. Move `actions.yaml` to `conf/actions/user.yaml`
5. Create `conf/actions/system.yaml` with predefined commands (time, date, restart, llm_chat, llm_learn) and `on_startup`
6. Add `conf/secrets.yaml` to `.gitignore`
7. Update `Taskfile.yml` and `setup/` references to new paths
8. Update tests

Rollback: `git revert` — old files were at project root, new files are in `conf/`. No database or external state to roll back.
