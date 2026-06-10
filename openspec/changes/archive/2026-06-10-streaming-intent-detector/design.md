## Context

Stage-1 (`_run_stt_loop`) runs a continuous Vosk free-vocabulary recognizer. Every audio chunk calls `stage1.PartialResult()`, which returns the current in-progress transcript. This partial is currently only forwarded to the web dashboard (`on_stt_event`). Wake matching only happens after the VAD fires or Vosk's endpoint detector fires — introducing 500–900ms of mandatory silence wait.

The `alias_map` (built by `_build_alias_map`) maps normalized wake phrases → `WakeWordGroup`. Each group holds per-group triggers; global triggers act as fallback. `_extract_wake_command(text, alias_map)` does an exact `startswith` check and returns `(group, inline_cmd)`. `_wake_detected` handles the rest (beep, stage-2 skip, action dispatch).

All the pieces needed for partial matching are already present — the loop just doesn't use them on partials.

## Goals / Non-Goals

**Goals:**
- Fire `_wake_detected` immediately when a partial transcript stably matches a complete `(wake + trigger)` intent
- Keep exact matching on partials (no fuzzy — premature firing on incomplete tokens)
- Build `intent_map` once at config load; rebuild on hot-reload
- Remain fully additive: existing VAD/endpoint/LLM fallback path unchanged
- Default enabled; disableable via `recognition.partial_matching: false`

**Non-Goals:**
- Fuzzy partial matching (deferred; add aliases instead)
- Sherpa-onnx KWS path (different code branch; unaffected)
- Grammar mode interaction (when `vosk_use_grammar=True`, partial matching is skipped — grammar already constrains vocabulary)
- Trigger phrase fuzzy matching (exact only for now)

## Decisions

### D1: Exact matching only on partials

**Decision:** `_match_full_intent` calls `_extract_wake_command(partial, alias_map, fuzzy=False)` then checks `inline_cmd` against trigger phrases with `normalize_text` equality.

**Rationale:** Vosk partials are mid-word tokens. `_approx_wake_match` scores by word-overlap — "ehi" alone in a partial matches "ehi galileo" at 0.5 threshold. The stability window can't compensate because the wrong match is stable while the user is still speaking. Exact matching with aliases in config is the safe path.

**Alternative considered:** Fuzzy on partials with a higher threshold (0.8). Rejected — word-overlap on incomplete tokens is fundamentally unreliable regardless of threshold.

### D2: Two-variable stability window

**Decision:** Track `_partial_stable_match` (last seen intent key) and `_partial_stable_reads` (consecutive read count). Fire when `reads >= partial_stability_reads` AND elapsed ms since first match `>= partial_stability_ms`.

**Rationale:** Reads-only is fragile (chunk size varies). Time-only misses rapid flickers that resolve within one chunk. Both together: reads catches 1-frame noise, time catches slow-revision artifacts.

**Defaults:** 3 reads, 150ms. At 32ms/chunk this means 3 consecutive matching partials spanning at least 150ms wall-clock — roughly one phoneme of stability.

### D3: Intent map keyed by normalized `"wake trigger"` string

**Decision:** `build_intent_map` returns `dict[str, tuple[WakeWordGroup, Trigger]]` where the key is `normalize_text(wake_phrase + " " + trigger_phrase)`.

**Rationale:** `_extract_wake_command` already normalizes text before startswith check. Matching the same normalization keeps the logic consistent and avoids a second normalization pass in the hot path.

**Structure:**
```
"ehi galileo chiama stefano"  →  (galileo_group, chiama_trigger)
"ehi galileo accendi le luci" →  (galileo_group, accendi_trigger)
"ehi assistente chiama stefano" → (assistente_group, chiama_trigger)
...
```

### D4: `build_intent_map` lives in `stt_phonetics.py`

**Decision:** Place alongside `_build_alias_map` — they share the same input shape (`alias_map` + trigger lists) and normalization logic.

**Rationale:** Keeps STT loop code (`stt.py`) free of map-building concerns. Both builders are called once at startup and on hot-reload from the same callsite.

### D5: Skip partial matching when `vosk_use_grammar=True`

**Decision:** When stage-1 uses grammar mode, the partial matching block is bypassed entirely.

**Rationale:** Grammar mode already constrains Vosk to known phrases; partial stability behavior in grammar mode is untested and the benefit is marginal. The existing path handles it correctly.

## Risks / Trade-offs

**Partial fires mid-utterance if Vosk stabilises on an intent before user finishes** → The user gets a slightly earlier response than expected. In practice this is desirable — it means the system recognised the intent the moment the words were complete. If the user added extra words, those are discarded (same as mode 2 today).

**Vosk partial revision after stability window** → Stability window (150ms / 3 reads) significantly reduces this. If Vosk does revise post-fire, `_wake_detected` has already been called. The subsequent VAD finalization will produce a mismatched result, but `_wake_detected` is already complete — no double-fire because `_reset_stage1()` is called immediately after the early exit.

**Hot-reload race** → `intent_map` is rebuilt in the config-reload check in `_run_stt_loop`. The map is a local variable read by the same thread, so no locking needed.

**Grammar mode regression** → Mitigated by D5 (skip partial matching entirely in grammar mode).

## Migration Plan

- `partial_matching` defaults to `true` — no config change needed to enable
- Existing `conf/config.yaml` users get the new behaviour automatically
- To opt out: add `recognition.partial_matching: false`
- No rollback complexity — it's a pure additive code path with a config flag

## Open Questions

- None blocking implementation. Post-ship: evaluate whether a small fuzzy threshold on the trigger phrase (not wake phrase) helps with ASR variants of common Italian commands.
