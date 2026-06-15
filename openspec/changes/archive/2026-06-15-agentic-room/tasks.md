## 1. Fix LLM Response Verbosity

- [x] 1.1 Reduce `max_tokens` from 200 to 80 in agent.py line 81
- [x] 1.2 Strengthen system prompt to enforce brevity: append "Massimo una frase, al massimo 15 parole." to the existing prompt
- [x] 1.3 Add `temperature=0.3` to reduce creative elaboration (line 80)

## 2. Prevent Echo Re-triggering

- [x] 2.1 Add a `_tts_cooldown_until` timestamp (in `_handle_llm` or via module-level state) that is set after `_speak()` completes, with a configurable cooldown window (e.g. 1000ms)
- [x] 2.2 In `_process_audio` loop, skip Vosk `AcceptWaveform` results when `time.monotonic() < _tts_cooldown_until`

## 3. Improve Vosk False-Positive Gating

- [x] 3.1 Add an RMS energy gate before accepting Vosk final results (skip if below a threshold like 0.02, matching the main daemon's stage1 RMS threshold)
- [x] 3.2 Log discarded low-energy segments for debugging

## 4. Make Agent Configurable (Future)

- [x] 4.1 Extract hardcoded values (Groq model, system prompt, max_tokens, temperature, TTS voice path) into constants or a small config block at the top of agent.py
- [x] 4.2 Remove hardcoded Groq dependency: reuse `alexa_custom.llm.OpenAIClient` instead of importing `openai` directly
