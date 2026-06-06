## Context

`alexa-custom` dispatches voice commands via a static trigger tree defined in `config.yaml`. When no trigger matches, the system plays a timeout tone and loops. There is no general-purpose conversational capability and no way to add new commands at runtime without editing YAML files by hand.

The system runs headless on a Qualcomm Snapdragon 801 (aarch64, limited RAM). Audio I/O is PipeWire-based. The existing `ask` action already demonstrates multi-turn voice interaction using a `listen_fn` callback — this design builds on the same mechanism. `config.yaml` is hot-reloaded every ~4 s by `config_manager.py`.

## Goals / Non-Goals

**Goals:**
- Free-form voice conversation via remote Ollama when no trigger matches
- Voice wizard to teach new commands, persisted to `actions.yaml`
- `actions.yaml` as the agent-writable source of truth for trigger/action definitions
- Zero behaviour change when `llm:` is absent from config
- Backward compatibility: existing inline `triggers:` in `config.yaml` still load

**Non-Goals:**
- Local LLM inference on the board
- `ask`-tree generation via the wizard (hand-edit only)
- Streaming token-by-token TTS (respond after full LLM reply)
- Multi-user conversation isolation
- GUI/web interface for learned commands

## Decisions

### D1 — `actions.yaml` schema: global + per-wake-word map

```yaml
# actions.yaml
triggers:             # global fallback (available to all wake words)
  - phrase: "test"
    actions:
      - type: log
        message: "ok"

wake_triggers:        # per-wake-word overrides keyed by wake word string
  galileo:
    - phrase: "buonanotte"
      actions:
        - type: say
          text: "Buonanotte"
```

**Why over alternatives:**
- _Flat global-only_: simpler but agent can't teach wake-word-specific commands, which is natural ("galileo, impara questo")
- _Full clone of config.yaml schema_: would require duplicating `wake_words:` list structure, creating sync risk
- _Chosen_: minimal new schema — only what's needed for the agent to write. Wake word names act as keys; the loader matches them against the existing `WakeWordGroup` list in `config.yaml`

### D2 — Backward-compatible loader merge strategy

Load order in `config_manager.py`:
1. Parse `config.yaml` as today (inline `triggers:` and `wake_words[x].triggers:` still accepted)
2. If `actions_file:` is set and the file exists, parse it
3. Merge: `actions.yaml`.`triggers` **appended after** inline triggers (inline takes precedence by matching order)
4. Merge: `actions.yaml`.`wake_triggers[word]` **appended after** inline per-group triggers

This means existing configs work unchanged. Migration is opt-in: move triggers to `actions.yaml` whenever convenient.

### D3 — `llm.py` module structure

```
OllamaClient
  async def chat(messages, model, timeout) -> str
  raises OllamaUnreachable on connection/timeout error

ConversationEngine
  __init__(config: LLMConfig, lang: str)
  async def reply(user_text: str) -> str
  - maintains rolling history (last context_turns pairs)
  - resets history if last call > context_window_secs ago
  - system prompt: concise, voice-appropriate, no markdown/lists
  - on OllamaUnreachable: return sentinel UNREACHABLE

LearnWizard
  async def run(listen_fn, say_fn, wake_word: str) -> Trigger | None
  - step 1: elicit trigger phrase
  - step 2: elicit action intent (free-form, LLM interprets)
  - step 3: loop over identified action types, elicit params
  - step 4: confirm summary via TTS, listen for yes/no
  - returns Trigger or None on cancel/timeout

ActionsFileStore
  def load(path) -> ActionsData          # global triggers + wake_triggers map
  def save(path, data: ActionsData)      # ruamel.yaml round-trip write
  def append_trigger(path, trigger, wake_word=None)
```

### D4 — LLM response format: plain text, no JSON

The `ConversationEngine` instructs the LLM to reply in plain prose suitable for TTS (no markdown, no lists, no special characters). The `LearnWizard` uses a separate system prompt that instructs structured extraction, but the wizard drives the conversation turn-by-turn so the LLM only needs to answer narrow questions ("what topic?") at each step — no complex JSON schema required.

**Why over JSON-mode extraction:** JSON mode would require a capable model. Plain prose + wizard-controlled Q&A works with smaller, faster models (e.g. `llama3.2:3b`) and degrades gracefully on slower hardware.

### D5 — LLM fallback hook in `stt.py`

Both `_run_two_stage` and `_run_single_stage` have `nomatch` branches that call `_play_timeout()` and `continue`. The fallback replaces this with:

```python
if trigger is None:
    on_stt_event("nomatch", {"transcript": command})
    if _llm_enabled(current_config):
        _dloop.run_until_complete(_llm_fallback(command, ...))
    else:
        _play_timeout()
    continue
```

`_llm_fallback` reuses the existing `_listen_fn` and `dispatch` infrastructure — it calls `ConversationEngine.reply()`, then speaks the result via the `say` action, then listens for a follow-up in a short loop (max `context_turns` exchanges before returning to wake-word listening).

### D6 — `llm_learn` as an explicit trigger action

Rather than detecting "teaching intent" from every free-form utterance (brittle), teaching is invoked explicitly:

```yaml
# in actions.yaml
triggers:
  - phrase: "impara nuovo comando"
    actions:
      - type: llm_learn
```

The `LearnWizard` runs as a structured multi-turn dialogue. This keeps the free-form `ConversationEngine` simple (no intent classification needed) and makes learning mode predictable.

### D7 — `ruamel.yaml` for `actions.yaml` writes

`ruamel.yaml` preserves comments, ordering, and formatting on round-trip. `actions.yaml` is human-editable and agent-writable; users should be able to annotate it without the agent destroying their comments.

**Alternative — append text blocks:** simpler, no new dependency, but produces ugly YAML and can't update existing entries. Rejected because the agent may eventually need to update or remove commands.

### D8 — Conversation context lifetime

A module-level `_last_interaction: float` timestamp in `llm.py` tracks the last `ConversationEngine.reply()` call. On each call, if `time.monotonic() - _last_interaction > context_window_secs`, history is cleared before appending the new message. This is transparent to the caller and requires no explicit "end session" command.

## Risks / Trade-offs

**[Latency]** Ollama round-trips over LAN add 1–5 s depending on model and hardware. TTS feedback ("sto pensando…") or a tone can mask the gap, but the interaction will feel slower than deterministic commands.
→ Mitigation: play a brief "thinking" tone before sending to Ollama; make the model configurable so users can choose speed vs quality.

**[Ollama unavailable]** If the Ollama host goes down mid-session, all unmatched commands hit a network timeout.
→ Mitigation: `request_timeout` config key (default 10 s); on timeout/error speak "agente remoto non raggiungibile" and return to wake-word loop.

**[actions.yaml write conflicts]** Hot-reload polls every 4 s. If the user edits `actions.yaml` at the same time the wizard writes it, one write may clobber the other.
→ Mitigation: `ActionsFileStore.save()` uses a write-to-temp-then-rename pattern to make writes atomic.

**[LearnWizard hallucination]** The LLM may misinterpret the user's intent and produce wrong action params.
→ Mitigation: the wizard always reads back the full command summary and requires explicit confirmation before writing. The user can say "no" or "annulla" to abort.

**[YAML injection via voice]** A user could speak shell metacharacters that end up in a `shell` action.
→ Mitigation: the wizard validates action types against an allowlist; `shell` command strings are stored verbatim as YAML strings (no shell expansion at learn time). At dispatch time, `shell` already passes commands to `subprocess` with `shell=True` — document that `shell` action type is privileged and should not be in the default wizard allowlist for untrusted environments.

**[Backward compatibility]** Inline `triggers:` in `config.yaml` remain supported but will not be updated by the agent.
→ Mitigation: log a one-time info message suggesting migration to `actions_file:` when inline triggers are detected alongside `llm.learn_commands: true`.

## Migration Plan

1. Add `actions_file: actions.yaml` to `config.yaml`
2. Move inline `triggers:` content to `actions.yaml` under `triggers:`
3. Move per-wake-word trigger lists to `actions.yaml` under `wake_triggers.<word>:`
4. Remove now-empty `triggers:` keys from `config.yaml`
5. Restart or wait for hot-reload

Steps 1–4 are fully optional — the loader accepts both forms indefinitely.

**Rollback:** remove `llm:` and `actions_file:` from `config.yaml`; restore inline `triggers:`. No schema migration required.

## Open Questions

- Should `llm_chat` action support an optional `system_prompt` override per-trigger, or only the global one from `LLMConfig`? (Proposed: yes, per-trigger override allowed)
- Should the wizard support adding commands to a specific wake word group, or always ask the user which group? (Proposed: default to the wake word group that triggered the `llm_learn` action)
- Should learned commands be visually distinguished in `actions.yaml` (e.g. under a `# --- learned ---` comment block)? (Proposed: yes, separator comment on first write)
