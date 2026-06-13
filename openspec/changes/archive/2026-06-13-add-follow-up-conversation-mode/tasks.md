## 1. Config surface

- [x] 1.1 Add `follow_up: bool = False`, `follow_up_timeout: float = 4.0`, `follow_up_max_turns: int = 5`, `follow_up_tone: str = "info"` to `RecognitionConfig` in `alexa_custom/config.py`
- [x] 1.2 Parse the four new keys in the `recognition:` block parser (mirror `command_timeout` / `wake_tone` handling; coerce types, apply defaults when absent)
- [x] 1.3 Add `follow_up: bool | None = None` to the `Trigger` dataclass
- [x] 1.4 Parse an optional `follow_up` key in trigger parsing (both `config.yaml` inline triggers and `conf/actions/*.yaml`): accept bool, default `None` when absent
- [x] 1.5 Document the new `recognition.follow_up*` keys and the per-trigger `follow_up` override in config comments / `docs/`

## 2. Refactor _wake_detected

- [x] 2.1 Extract the capture→match→dispatch tail of `_wake_detected` (`alexa_custom/stt.py`, ~lines 1139–1239) into `_handle_command(transcript: str) -> bool` returning whether a trigger matched (or LLM fallback fired)
- [x] 2.2 Preserve exactly: the MQTT `command` publish, `metrics.inc("commands_matched")`, `on_stt_event` calls (`nomatch`/`matched`), the `fallback_on_no_match` → `llm_chat` branch, and the matched-dispatch branch
- [x] 2.3 Verify existing tests for `_wake_detected` / dispatch still pass after the pure refactor (no behavior change yet)

## 3. Follow-up loop

- [x] 3.1 Add a `_follow_up_active(trigger, config) -> bool` helper: return `trigger.follow_up` if not `None`, else `config.recognition.follow_up`; treat `llm_chat`-only triggers as inactive (they own their own multi-turn loop)
- [x] 3.2 In `_wake_detected`, after the first `_handle_command`, loop while active, matched, not `livekit_connected_flag.is_set()`, and under `follow_up_max_turns`
- [x] 3.3 Each loop iteration: `_drain_pipe(proc)`, play `follow_up_tone`, publish `listening` state (MQTT + `on_stt_event`), then `capture_transcript(..., config.recognition.follow_up_timeout, ...)`
- [x] 3.4 Break on empty transcript (silence); break on `is_exit_phrase(transcript, exit_phrases)` (import from `alexa_custom/llm.py`); otherwise `matched = _handle_command(transcript)` and continue
- [x] 3.5 On loop exit, return to idle/wake-listening exactly as the non-follow-up path does today (state publish, stage-1 reset handled by the caller loop)

## 4. Tests

- [x] 4.1 Follow-up disabled by default: a matched command does not open a follow-up window (behavior identical to today)
- [x] 4.2 Follow-up enabled: a second command is dispatched without a wake word after the first
- [x] 4.3 Silence closes the window (empty follow-up capture → return to idle)
- [x] 4.4 Exit phrase closes the window without dispatch
- [x] 4.5 `follow_up_max_turns` cap: window closes after N consecutive turns
- [x] 4.6 Per-trigger override: `follow_up: false` suppresses window when global is on; `follow_up: true` opens window when global is off
- [x] 4.7 Suppression: window does not open when `livekit_connected_flag` is set
- [x] 4.8 Echo safety: a follow-up after a TTS-confirming action drains the pipe first (assert `_drain_pipe` called before the follow-up `capture_transcript`)
- [x] 4.9 No-match in a follow-up turn with `fallback_on_no_match` routes to `llm_chat`; without it, closes with timeout tone
- [x] 4.10 Config parsing: follow-up fields default correctly when absent; per-trigger `follow_up` parses to `True`/`False`/`None`

## 5. Validation

- [x] 5.1 Run `task test` and `task lint` for final validation
- [ ] 5.2 Manual smoke on the board: enable `follow_up`, verify two chained commands without re-waking, and verify a TTS-confirming action does not echo-trigger a phantom follow-up turn
