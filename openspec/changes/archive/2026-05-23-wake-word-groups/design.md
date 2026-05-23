## Context

`stt.py` currently builds a Vosk grammar from `config.wake_words` (a flat `list[str]`) and, after wake detection, looks up the command against `config.triggers` (a single global list). Both the grammar and the trigger table are rebuilt on every hot-reload.

The two touch points that need changing are:
1. **`_grammar_json`** — currently takes `list[str]`; needs to flatten all words and aliases from all groups
2. **`match_trigger` call sites** — currently use `config.triggers`; need to use the matched group's trigger list, falling back to `config.triggers`

The `_extract_wake_command` helper (used in single-stage mode) and the two-stage wake detection loop both resolve a detected text to a wake word string; they need to resolve to a `WakeWordGroup` instead.

## Goals / Non-Goals

**Goals:**
- Each `WakeWordGroup` has a primary `word`, optional `aliases`, and an optional `triggers` list
- Grammar includes all words and aliases from all groups
- After detection, the system knows which group fired and uses its trigger list
- Empty group triggers → fall back to global `config.triggers`
- Hot-reload works unchanged (grammar and lookup rebuilt on every reload)

**Non-Goals:**
- Per-group `command_timeout`, `wake_confidence`, or `recognition_mode` (single global values remain)
- Overlapping aliases across groups (undefined behaviour, first match wins)
- UI grouping of wake words in the web dashboard

## Decisions

### D1: `WakeWordGroup` dataclass with optional `triggers`

```python
@dataclass
class WakeWordGroup:
    word: str                      # primary name (also a recognition phrase)
    aliases: list[str]             # additional recognition phrases → same group
    triggers: list[Trigger]        # empty list = use global fallback
```

`ActionsConfig.wake_words` changes from `list[str]` to `list[WakeWordGroup]`.
`ActionsConfig.triggers` is kept as the global fallback (may be empty if every group has its own triggers).

### D2: Pre-built alias → group lookup dict in stt.py

Build `dict[str, WakeWordGroup]` at the start of each STT loop iteration (after hot-reload check):

```python
alias_map = {
    normalize_text(phrase): group
    for group in config.wake_words
    for phrase in [group.word] + group.aliases
}
```

This replaces the linear scan in `_extract_wake_command` and the `next(w for w in config.wake_words ...)` pattern in the two-stage loop. Lookup is O(1) and the map is cheap to rebuild.

**Alternative considered**: attach the group reference at grammar-recognition time. Rejected — Vosk only returns the matched text, not which grammar token matched, so post-lookup is unavoidable.

### D3: Trigger resolution helper

```python
def _resolve_triggers(group: WakeWordGroup, fallback: list[Trigger]) -> list[Trigger]:
    return group.triggers if group.triggers else fallback
```

Called at every `match_trigger` site, replacing the bare `config.triggers` argument.

### D4: Grammar still a flat list

`_grammar_json` is updated to accept `list[WakeWordGroup]` and flatten internally:

```python
def _grammar_json(groups: list[WakeWordGroup]) -> str:
    phrases = [p for g in groups for p in [g.word] + g.aliases]
    return json.dumps(phrases + ["[unk]"])
```

No other callers; signature change is internal.

### D5: YAML schema — `word` key, not bare string

```yaml
wake_words:
  - word: galileo
    aliases: [hey galileo, galileo galileo]
    triggers:
      - phrase: chiama stefano
        actions: [...]
  - word: assistente          # no aliases, no triggers → uses global fallback
```

Old format (`wake_words: [galileo, assistente]`) is **not** supported after this change. `config.yaml.example` is the migration guide.

## Risks / Trade-offs

- **Breaking config change** → any existing `config.yaml` using the old flat list will fail to parse with a clear error. Mitigation: update `config.yaml.example`; error message points to the new format.
- **Alias collision** → if two groups share an alias, the first group wins (dict insertion order). Mitigation: log a warning at parse time when a duplicate alias is detected.
- **Empty fallback and empty group triggers** → if a group has no triggers AND global `triggers` is also empty, the command window opens but nothing ever matches. This is valid (e.g., a wake word that only triggers a LiveKit join via a different path). No error needed.

## Migration Plan

1. Update `config.py` — add `WakeWordGroup`, update `ActionsConfig`, update parser
2. Update `stt.py` — `_grammar_json`, alias map, trigger resolution at all call sites
3. Update `config.yaml.example`
4. Update tests that construct `ActionsConfig` directly with the old `wake_words: list[str]` shape
