## Context

The `che giorno è` trigger in `conf/actions/system.yaml` uses `$(date +'…')` shell templates via `_render_text()` in `actions.py`. On the target board (Arduino Uno Q, Debian Trixie), the systemd user service runs without `LANG=it_IT.UTF-8`, so `date` emits English day/month names. Fixing the locale system-wide (or per-service) requires `it_IT.UTF-8` to be generated on Debian and adds a brittle dependency on the board's locale configuration.

## Goals / Non-Goals

**Goals:**
- Add a `say_date` action type that speaks the current date with Italian day/month names
- Total independence from system locale (`date`, `locale-gen`, `LANG`)
- Follow existing `ActionRegistry` pattern and `say` action conventions

**Non-Goals:**
- Not adding a general-purpose templating engine to `_render_text()`
- Not changing the `say` action or `_render_text()` mechanism

## Decisions

| Decision | Choice | Alternatives |
|---|---|---|
| New action type vs. templating | New type `say_date` — clean separation, testable, self-documenting | Adding `{{weekday}}` to `_render_text()` would mix shell templates with Python templates |
| Hardcoded lists vs. `locale` module | Hardcoded `_WEEKDAYS_IT` / `_MONTHS_IT` lists — zero imports, trivially verifiable | `locale.setlocale(locale.LC_TIME, 'it_IT.UTF-8')` would reintroduce the same dependency |
| Format string syntax | `{weekday} {day} {month} {year}` — Python `str.format()`, no deps | Custom `$datefmt` would add parsing complexity |
| `weekday` index | `datetime.now().weekday()` (Monday=0) — matches ISO standard, `_WEEKDAYS_IT` indexed accordingly | `isoweekday()` gives Monday=1, would waste index 0 |

## Risks / Trade-offs

- **[Low] Date formatting limited to 4 fields** — if someone wants `{weekday_abbr}` or ordinal `{day}/{month}`, the format string and lists are easy to extend later. No breaking change.
- **[None] Locale dependency** — completely eliminated. The lists are in source control.
