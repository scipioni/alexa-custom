## Context

Action files currently split triggers across two top-level keys: `triggers` (global, active after any wake word) and `wake_triggers` (a dict keyed by wake-word group id). Direct-match triggers (stage-1 STT, no wake word needed) are distinguished by a `direct_match: true` flag on each individual trigger entry.

This creates three problems:
1. The scope of a trigger is not co-located with the trigger — you have to look at which key it lives under.
2. A trigger cannot be assigned to multiple specific wake words without duplication.
3. `direct_match` is easy to forget and silently absent defaults to a different behaviour.

The refactor moves scope declaration onto the trigger itself via a `wake_words` field, resolved at parse time into the same internal slots the runtime already uses.

## Goals / Non-Goals

**Goals:**
- Single `triggers:` list in action files; scope declared per trigger via `wake_words`
- `wake_words: []` replaces `direct_match: true` (unified semantics)
- A trigger can be assigned to multiple wake-word group IDs in one entry
- Runtime code (`client.py`) is minimally affected — same internal data structure
- Inline `triggers:` inside `wake_words:` groups in `config.yaml` unchanged

**Non-Goals:**
- Changing how trigger matching works (fuzzy, glob patterns, aliases)
- Backward compatibility shim for old `wake_triggers` key
- Changing `config.yaml` wake-word group schema

## Decisions

### D1 — Parse-time resolution, not runtime routing

`wake_words` is resolved during config loading and discarded. The runtime data structure stays the same:
- `ActionsConfig.triggers` — global triggers (checked after any wake word)
- `ActionsConfig.direct_triggers` — direct-match triggers (checked in stage-1)
- `WakeWordGroup.triggers` — per-group triggers (checked after that specific wake word)

**Why**: `client.py` already has the three-slot lookup. Keeping that unchanged minimises risk and diff.  
**Alternative rejected**: carry `wake_words` on `Trigger` at runtime and route dynamically — adds coupling and requires changes deep in the client loop.

### D2 — `wake_words: None` (absent) means global, `[]` means direct

`None` (field absent in YAML) and `["global"]` both resolve to the global slot. Empty list `[]` resolves to the direct-match slot.

**Why**: Most existing triggers have no scope declaration and are global — making absent = global preserves backward compat for the YAML value of `triggers:` lists (no `wake_words` field required). Using a sentinel string `"global"` allows explicit annotation without changing behaviour.

### D3 — `direct_match: bool` removed from `Trigger` dataclass

The flag is replaced entirely by `wake_words: []`. There is no migration shim — both old format keys (`wake_triggers`, `direct_match`) are removed in the same change.

**Why**: A shim that accepts both forms is dead weight and makes the parser harder to read. The config files are small and can be updated in the same PR.

### D4 — `ActionsData.wake_triggers` dict removed

`_load_actions_dir` no longer accumulates a `wake_triggers` dict. Instead, all triggers are collected in a single list and resolved during `_parse_actions_config`.

**Why**: The dict was only used to merge into `WakeWordGroup.triggers` at the end of `_parse_actions_config`. With per-trigger `wake_words`, the merge logic is a simple loop over the flat list.

## Risks / Trade-offs

- **Breaking change to all action files** → Mitigated: only `conf.example/actions/user.yaml` ships in the repo; user-owned files are updated in the same commit. The parser will warn (or error) on unknown `wake_triggers` key.
- **`direct_match` removed without deprecation period** → Acceptable: the flag is internal config, not a public API. All usages are in example files and tests within the same repo.
- **`wake_words: []` vs `wake_words` absent is visually easy to confuse** → Mitigated: the spec and example file make the distinction explicit; a parser warning on `direct_match: true` will guide migration.

## Migration Plan

1. Update `Trigger` dataclass: add `wake_words: list[str] | None`, remove `direct_match: bool`.
2. Update `_parse_triggers` to read `wake_words`; emit a warning if `direct_match` is present.
3. Update `_load_actions_dir` / `ActionsData`: remove `wake_triggers` dict; all triggers go into a single flat list carrying their `wake_words`.
4. Update `_parse_actions_config`: resolve the flat list into the three slots (`direct_triggers`, group triggers, global triggers).
5. Add `direct_triggers: list[Trigger]` to `ActionsConfig`.
6. Update `client.py`: replace `trigger.direct_match` filter with `config.direct_triggers` list lookup.
7. Update `conf.example/actions/user.yaml`: convert `wake_triggers` block and `direct_match` flags.
8. Update tests.

Rollback: revert the commit. No persistent state is affected (config files are user-owned and version-controlled).
