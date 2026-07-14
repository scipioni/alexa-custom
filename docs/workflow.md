# Development & Production Workflow

How to work on serena **locally** (dev machine) and how to deploy and operate it **in production** (the Arduino Uno Q board). Installation details live in [setup_software.md](setup_software.md); this document is about the day-to-day procedure.

| | Local (development) | Production (board) |
|---|---|---|
| OS | Arch Linux | Debian 13 (Trixie) |
| Hardware | any PC, no speakerphone needed | Arduino Uno Q + USB conference speakerphone |
| Runs as | `task run` / pytest in the foreground | `serena` systemd **user** service |
| Config | `conf/` (gitignored, copy of `conf.example/`) | `conf/` on the board + `conf/state.yaml` (calibration results) |

---

## 1. Local procedure (development)

### 1.1 One-time setup

```bash
git clone <repo> && cd serena
uv sync --group dev          # venv + dev dependencies
cp -r conf.example conf      # local config (gitignored)
```

System packages (GStreamer, audio tools): see [setup_software.md](setup_software.md), section "Arch Linux".

### 1.2 The development loop

```bash
# 1. branch from one-model/main
git checkout -b my-change

# 2. edit code, then run ONLY the tests relevant to the change
uv run pytest tests/test_wake_detection.py            # single file
uv run pytest tests/test_stt.py -k "TestVoskCheck"    # single class/test

# 3. matching changes? run the corpus regression gate
task eval                    # must stay 100% precision / 100% recall
                             # add new false wakes to tests/eval/corpus.yaml,
                             # never work around them in code

# 4. final validation before committing (full suite, ~4 min)
task fix                     # ruff fix + format + full pytest
```

Rules that keep the loop fast and honest:

- **Do not run the full suite while iterating** — it takes minutes; use targeted tests and save `task test` / `task fix` for the end.
- **Commit messages**: `feat:` / `fix:` prefixes end up in the auto-generated changelog; no `Co-Authored-By` trailer.
- **Semantic versioning**: releases are cut with `task release:patch|minor|major` (bumps `pyproject.toml`, updates `CHANGELOG.md`, tags). Push with `git push && git push --tags`.

### 1.3 Testing STT/TTS without the board or a microphone

- `serena-stt --play file.wav` replays a WAV through the **real** recognition loop (wake detection, fast endpoint, command matching included). Synthesize test phrases with Piper, resample to 16 kHz mono s16le, append ≥ 2 s of silence.
- `task test-stt-e2e` synthesizes speech with Piper and feeds it through the configured STT backend.
- `task eval` scores wake/command matching against the labelled corpus — pure text level, no audio needed.
- Pipeline-level integration tests (`tests/test_pipeline_e2e.py`, `tests/test_recognition_loop_logic.py`) use a scripted backend — no model, no mic.

What you **cannot** test locally: everything in "Host Audio Management & Workarounds" (AGENTS.md) — PipeWire profiles, mixer resets, USB autosuspend, Bluetooth-dongle behaviour. Those need the board and the real speakerphone.

---

## 2. Production procedure (the board)

### 2.1 First install

```bash
# on the board, as the regular user (systemd user services need lingering)
sudo loginctl enable-linger $(whoami)

git clone <repo> ~/serena && cd ~/serena
task init        # = task setup + task audio:setup + task audio:restart
                 # aborts on Arch by design — board only
```

`task init` does, in order:

1. **`task setup`** — `uv sync`, Italian locale + Rome timezone, installs and enables the `serena` systemd user service.
2. **`task audio:setup`** — device-agnostic audio configuration: detects any USB conference speakerphone (NewPie, Yealink, EMEET, ...), selects the best card profile, installs the restore service (`alsa-pcm-unmute.service` → `serena-usb-audio-restore`), the udev no-autosuspend + replug-recovery rule, and the WirePlumber no-suspend rule. Run once; survives reboots and replug.
3. **`task audio:restart`** — applies routing/mixer state now.

Then:

```bash
cp -r conf.example conf                  # if conf/ does not exist yet
$EDITOR conf/secrets.yaml                # LiveKit, Telegram, LLM, MQTT credentials
$EDITOR conf/config.yaml                 # wake words; audio devices stay on 'auto'
systemctl --user restart serena
```

Device-specific notes (Yealink SP92 direct-USB needs a manual `pro-audio` profile, BT51 works out of the box, ...): see AGENTS.md, "Yealink SP92 / BT51 Device Profile".

### 2.2 Microphone calibration (recommended after install or moving the device)

Say **"ehi serena, calibra microfono"** and follow the voice prompts. The procedure sweeps hardware gain and GStreamer filter variants, scoring every candidate under each configured condition (near speech, far speech — add e.g. a TV-on condition in `conf/actions/system.yaml`), and picks the **worst-case** winner. Takes ~3 minutes / 13 spoken phrases.

Results are persisted in `conf/state.yaml` (`input_gain`, `gstreamer_override`) and take precedence over the named GStreamer profile. To discard a calibration, delete those keys and restart.

### 2.3 Updating production

```bash
cd ~/serena
git pull
uv sync                       # only needed when dependencies changed
systemctl --user restart serena
```

- Re-run `task audio:setup` only when files under `setup/` changed (the changelog/commit messages say so) or when swapping the speakerphone hardware.
- `conf/` is gitignored: compare with `conf.example/` after big updates for new keys (`diff -u conf.example/config.yaml conf/config.yaml`).
- Config edits alone need **no deploy step**: `conf/config.yaml` and `conf/actions/*.yaml` are hot-reloaded (~4 s poll). Code changes require a service restart.

### 2.4 Verification & operations

```bash
task audio:status                     # USB card, active profile, default routing
task audio:doctor                     # every audio invariant, pass/fail
systemctl --user status serena       # service state
journalctl --user -fu serena         # live logs (transcripts at LOG_LEVEL=DEBUG)
```

- Web dashboard: `http://<board>:8080` (config panel under `/config`, dev-mode toggle).
- Audio dropped mid-session → `task audio:restart`.
- First command after idle misheard → verify `agc` is still `false` in the yealink GStreamer profile AND in `conf/state.yaml` `gstreamer_override` (see AGENTS.md, AGC failure modes).
- Recognition debugging → enable `actions.dump_triggers_dir` in `conf/config.yaml`; every match dumps an 8 s pre-trigger WAV, analyzed with `task stt:analyze-dumps`. Disable it afterwards.
- More: [troubleshooting.md](troubleshooting.md).

### 2.5 Releasing

On the dev machine:

```bash
task release:patch        # or release:minor / release:major
git push && git push --tags
```

Then update the board (§ 2.3). `task release:rollback` undoes the latest release tag/commit if needed.

---

## 3. Quick reference

| I want to... | Local | Production |
|---|---|---|
| run the app | `task run` | `systemctl --user restart serena` |
| run tests | `uv run pytest tests/test_x.py` | — (don't test on the board) |
| validate matching | `task eval` | say a wake word, watch `journalctl` |
| check audio | — | `task audio:doctor` |
| tune the mic | — | "ehi serena, calibra microfono" |
| ship a change | `task fix` → commit → push | `git pull` → restart service |
| cut a release | `task release:patch` | `git pull` after tag |
