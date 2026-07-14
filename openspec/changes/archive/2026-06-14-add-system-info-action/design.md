## Context

The action registry in `alexa_custom/actions.py` uses a `@registry.register("type")` decorator pattern. Each handler is an `async def` receiving `action: ActionEntry` plus keyword deps (`mqtt_client`, `transcript`, etc.) via `**_`. The `meteo` and `calibrate_input_gain` actions are the closest analogues — they do I/O, format a string, and speak it via `asyncio.to_thread(get_engine().say, text, lang)`.

System vitals are available from standard Linux pseudo-files — no extra dependencies needed.

## Goals / Non-Goals

**Goals:**
- Read CPU temp, load avg, free RAM, uptime from `/proc`/`/sys`
- Speak one Italian sentence via the existing TTS engine
- Degrade gracefully when a source is unavailable (e.g. no thermal zone)

**Non-Goals:**
- Configurable params (lang, subset of vitals) — always Italian, always all vitals
- MQTT state broadcast beyond what other simple actions do
- Writing or persisting stats anywhere

## Decisions

**Reading vitals synchronously in `asyncio.to_thread`**
All file reads are synchronous `/proc`/`/sys` reads — microsecond latency. Wrap the entire read+format block in a single `asyncio.to_thread` call alongside the TTS call, keeping the async handler clean.

Alternative: read inline in the async handler (no thread needed for `/proc` reads). Acceptable too, but `to_thread` keeps the pattern consistent with other handlers.

**CPU temperature source**
Read all `/sys/class/thermal/thermal_zone*/temp` files, take the maximum value (most conservative). On the Snapdragon board there are multiple zones; max gives the hottest point. If none readable, omit temperature from the sentence.

**Italian number formatting**
Use integer rounding for temperature (°C) and load (one decimal). For memory, convert to GB with one decimal if ≥ 1 GB, otherwise MB. For uptime, express in natural Italian: "un giorno e tre ore", "quarantadue minuti", etc. — not raw seconds.

**Uptime phrasing**
Read `/proc/uptime` (first field = seconds since boot). Convert to days/hours/minutes. Speak only the two most significant non-zero units to keep the sentence short.

## Risks / Trade-offs

- [Thermal zone path varies by board] → Use glob to find all zones, take max; fall back gracefully if none found.
- [Italian number words for large memory values] → Keep it simple: round to nearest integer GB for values ≥ 1 GB.
- [TTS latency while reading /proc] → negligible; `/proc` reads are sub-millisecond.

## Open Questions

- None — scope is fully determined.
