## 1. Implementation

- [x] 1.1 Add `_WEEKDAYS_IT` and `_MONTHS_IT` constant lists to `alexa_custom/actions.py`
- [x] 1.2 Add `handle_say_date()` handler with `@registry.register("say_date")` using `datetime.now()`, `str.format()`, and TTS via `get_engine().say()`
- [x] 1.3 Update `conf/actions/system.yaml` — replace `che giorno è` action from `say` + shell template to `say_date`
- [x] 1.4 Update `conf.example/actions/system.yaml` — same change for reference config

## 2. Tests

- [x] 2.1 Add test verifying handler is registered in the registry
- [x] 2.2 Add test that `say_date` returns correct Italian weekday/month names with mocked `datetime`
- [x] 2.3 Add test that a custom `format` parameter overrides the output
