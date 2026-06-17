## Context

The existing `llm_chat` action (in `actions.py:622`) uses `ConversationEngine.reply_streaming()` which sends user text to the LLM and streams token output directly to TTS. There is no mechanism for the LLM to invoke system actions mid-conversation. The `LearnWizard` class in `llm.py` already proves the LLM can parse user intents into structured action types, but it does so via a secondary non-streaming API call — not within the conversational flow.

The system already has a complete `ActionRegistry` with 15+ handlers (`shell`, `mqtt_publish`, `set_volume`, `meteo`, `system_info`, `telegram`, `say`, `tone`, `livekit_join`, etc.). These are currently only reachable via static YAML trigger matching or MQTT commands.

Both Ollama (`/api/chat`) and OpenAI-compatible (`/v1/chat/completions`) APIs natively support a `tools` parameter that lets the model request function execution. The CrofAI API speaks OpenAI-compatible format and the existing `OpenAIClient` can be used directly.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                      AGENTIC LLM CHAT FLOW                              │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────┐    listen()    ┌─────────────────────────────────────────────┐
│  User    │───────────────▶│  handle_llm_chat_agentic (actions.py)      │
│  speaks  │                │                                             │
└──────────┘                │  1. Send user text + context to LLM         │
         ▲                  │     with tools=[...tool_definitions]        │
         │                  │                                             │
         │                  │  2. LLM responds:                           │
         │                  │     a) tool_calls → execute via registry    │
         │                  │        → feed result back → goto 2          │
         │                  │     b) text content → stream to TTS, done   │
         │                  │                                             │
         │                  │  ┌──────────────────────────┐               │
         │                  │  │  AgenticLoopEngine        │               │
         │                  │  │  (new class in llm.py)    │               │
         │                  │  │                           │               │
         │                  │  │  Tool definitions ────────┤               │
         │                  │  │  Tool dispatcher          │               │
         │                  │  │  Result re-feed           │               │
         │                  │  │  Max iterations guard     │               │
         │                  │  └────────────┬──────────────┘               │
         │                  │               │                              │
         │    TTS say()     │               │ dispatch                     │
         │◁────────────────│               ▼                              │
         │                  │     ┌──────────────────┐                    │
         │                  │     │ ActionRegistry   │                    │
         │                  │     │ .execute(type,   │                    │
         │                  │     │   **kwargs)      │                    │
         │                  │     └──────────────────┘                    │
         │                  │               │                              │
         │                  │         ┌─────┴─────┐                       │
         │                  │         ▼           ▼                       │
         │                  │   shell()    mqtt_publish()  ...            │
         └──────────────────┘   (allowlist)  (raw)
```

## Goals / Non-Goals

**Goals:**
- LLM can invoke any existing `ActionRegistry` handler via natural conversation
- Tool definitions auto-generated from registry metadata (no manual duplication)
- Shell commands restricted to a configurable allowlist
- Final LLM response streamed to TTS as usual
- Works with both OpenAI-compatible (CroFAI) and Ollama backends
- Original `llm_chat` action preserved for non-agentic use

**Non-Goals:**
- Not replacing the static YAML trigger system — triggers and agentic chat coexist
- No streaming during tool calls (LLM response must resolve before TTS)
- No parallel tool execution (sequential only for predictability)
- No persistent tool state across conversation turns (stateless tool calls)

## Decisions

### 1. New `AgenticLoopEngine` class in `llm.py`

Rather than overloading `ConversationEngine`, a separate class owns the tool-calling loop. `ConversationEngine` stays clean: it handles history, system prompts, and streaming. `AgenticLoopEngine` wraps it and adds the tool layer.

**Why not modify `ConversationEngine.reply_streaming()`?** The streaming contract (yield tokens → TTS mid-flight) conflicts with tool calls (stop streaming, execute, resume). A wrapper is cleaner than making `reply_streaming` conditionally non-streaming.

### 2. Tool definitions from `_ACTION_PARAMS` + `_WIZARD_ALLOWED_TYPES` metadata

The existing `_ACTION_PARAMS` dict in `llm.py` (line 29) and `_WIZARD_ALLOWED_TYPES` set (line 17) already describe action types and their required params. These are extended with optional params, descriptions, and JSON Schema formatting.

**Why not auto-generate from `ActionRegistry`?** The registry's `execute()` method is a keyword-arg pass-through with no introspection. Adding JSON Schema metadata to each handler function would be invasive. The existing metadata dicts in `llm.py` are the right place — they already serve a similar purpose for LearnWizard.

### 3. Shell allowlist as a config list

A new `shell_allowed_commands` list in LLM config. Each entry is a glob pattern like `"publish *"`, `"uptime"`, `"date"`. The agentic wrapper checks the command against all patterns before dispatching.

**Why glob patterns instead of exact strings?** Allows wildcard patterns like `"mosquitto_pub *"` while keeping `"rm -rf /"` blocked.

### 4. Non-streaming during tool loop, streaming for final response

The `AgenticLoopEngine` calls `OllamaClient.chat()` (non-streaming) for tool-calling turns. Once the LLM produces a text-only response (no more `tool_calls`), it calls `ConversationEngine.reply_streaming()` for TTS output.

**Why not stream tool calls too?** The `tools` parameter returns `tool_calls` as a batch at the end of a response. There's no incremental delivery. The model either emits text or tool_calls, not both interleaved.

### 5. Max tool iterations (default 5) to prevent infinite loops

A safety counter. If the LLM keeps calling tools without producing a final response, the loop terminates and a fallback message is spoken.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| LLM hallucinates tool names or params | Tool definitions use strict JSON Schema; invalid params = error result fed back |
| Infinite tool-calling loop | Hard cap of 5 iterations; spoken "Non riesco a completare l'operazione" |
| Shell command injection via allowlist bypass | Glob patterns are checked with `fnmatch`; no eval/subprocess tricks possible |
| API costs on CrofAI for multi-turn tool loops | Each tool call = 1 round trip. With max 5 iterations, worst case = 6 LLM calls per user turn |
| Model doesn't support `tools` parameter | Falls back to non-agentic mode; logs warning |

## Open Questions

- Should the tool definitions be hardcoded or annotated on registry handlers? (Decision above: metadata dicts for now)
- Should TTS speak tool execution results? (E.g. "Ho acceso la luce" vs just executing silently)
