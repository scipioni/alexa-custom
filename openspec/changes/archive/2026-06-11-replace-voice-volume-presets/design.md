## Context

Three volume voice commands currently exist: two incremental ones (`alza il volume`, `abbassa il volume` in `conf.example/actions/user.yaml`) and one transcript-parsing one (`volume al` in `conf.example/actions/system.yaml`). The transcript-parsing approach introduced a dedicated action type (`set_volume_from_transcript`) and a `number_parser` module. A side effect of `save_volume_config()` writing to `config.yaml` triggers the web asset watcher to broadcast `{"type": "reload"}`, which the client JS interprets as `location.reload()`.

The `set_volume` action type already supports `mode: absolute` with a `value` parameter, making the transcript-parsing infrastructure unnecessary.

## Goals / Non-Goals

**Goals:**
- Replace three old commands with three absolute preset commands using only YAML changes
- Remove all dead code: `handle_set_volume_from_transcript`, `number_parser`, associated tests, archived change
- Fix the page-reload bug triggered by volume changes

**Non-Goals:**
- No changes to the `set_volume` action handler or the `@registry.register` mechanism
- No changes to audio hardware volume persistence (`save_volume_config` continues to write to config.yaml as before)
- No new translations or locale support

## Decisions

### 1. New triggers in `system.yaml`
The new presets replace the old `volume al` entry directly in `system.yaml`. This keeps all volume-related triggers in one place and maintains the convention that `system.yaml` holds the canonical set of trigger entries distributed with the project.

### 2. All three use `set_volume` with `mode: absolute`
No new action type needed. The YAML config for each:

```yaml
- phrase: "Volume basso"
  actions:
    - type: set_volume
      mode: absolute
      value: 0.1
- phrase: "Volume medio"
  actions:
    - type: set_volume
      mode: absolute
      value: 0.5
- phrase: "Volume alto"
  actions:
    - type: set_volume
      mode: absolute
      value: 0.9
```

### 3. Two-line fix for the page reload
The `_asset_watcher_loop` broadcasts `{"type": "reload"}` for any file change (YAML or HTML). The JS unconditionally does `location.reload()`. Solution: remove the broadcast line (`web.py:392`) and the JS handler (`dashboard.html:1537`). The HTML is already hot-reloaded in-memory server-side; the client doesn't need to reload.

### 4. `set_volume_from_transcript` removal is complete
Remove the `@registry.register` handler, the `number_parser` module (no other imports), all test cases, and the archived change directory.

## Risks / Trade-offs

- **Archived change deletion** — Losing the design history of `set_volume_from_transcript`. Acceptable since git history retains it.
- **Italian phonetic collision** — `volume basso` → phonetic `volume baso`, `volume medio` → `volume medio`, `volume alto` → `volume alto`. No overlap with other trigger phrases.
