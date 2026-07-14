## 1. Data model (config.py)

- [x] 1.1 Add `wake_words: list[str] | None = None` field to `Trigger` dataclass; remove `direct_match: bool`
- [x] 1.2 Add `direct_triggers: list[Trigger]` field to `ActionsConfig` dataclass
- [x] 1.3 Remove `wake_triggers: dict[str, list[Trigger]]` from `ActionsData`; add `direct_triggers: list[Trigger]`

## 2. Parser (config.py)

- [x] 2.1 Update `_parse_triggers`: read `wake_words` from raw dict; emit a warning if `direct_match` key is present (removed field)
- [x] 2.2 Update `_load_actions_dir`: remove `wake_triggers` accumulation; warn if `wake_triggers` key present; add `wake_words:` list parsing to define new groups in action files; collect all triggers into a single flat list
- [x] 2.3 Update `_parse_actions_config`: replace `wake_triggers` merge loop with a single pass over the flat trigger list — route `wake_words: []` → `direct_triggers`, `wake_words` absent/global → `ActionsConfig.triggers`, named ids → matching `WakeWordGroup.triggers`
- [x] 2.4 Remove `_merge_user_wake_words` function and `conf/user.yaml` lookup from `_parse_actions_config`

## 3. STT stage-1 direct trigger lookup (stt.py)

- [x] 3.1 Replace `[t for t in config.triggers if t.direct_match]` (stt.py:958) with `config.direct_triggers`

## 4. LLM command learning (llm.py)

- [x] 4.1 Update `llm.py` learned-command writer: replace the `wake_triggers` key it writes with a trigger entry using `wake_words: [<group_id>]`

## 5. Web dashboard (web.py + dashboard.html)

- [x] 5.1 Update `web.py` trigger serialisation (web.py:809): replace `"direct_match": t.direct_match` with `"direct_match": t in config.direct_triggers` (or derive from `wake_words` being `[]` before resolution)
- [x] 5.2 Update `dashboard.html`: no behaviour change needed — `direct_match` boolean in the serialised JSON is kept; JS logic is unchanged

## 6. Example config + docs

- [x] 6.1 Update `conf.example/actions/user.yaml`: convert `wake_triggers:` block to inline triggers with `wake_words: [help]`; convert any `direct_match: true` entries to `wake_words: []`; add `wake_words:` section for the `help` group
- [x] 6.2 Remove `conf.example/user.yaml`
- [x] 6.3 Update `conf.example/config.yaml`: remove reference to `conf/user.yaml` in comments
- [x] 6.4 Update `docs/configuration.md`: replace `wake_triggers` example with `wake_words` field; document `wake_words:` in action files; remove `conf/user.yaml` mention
- [x] 6.5 Update `CLAUDE.md`: update Configuration section schema example to use new trigger format

## 7. Tests (tests/test_config.py)

- [x] 7.1 Update `test_wake_triggers_merged`: rewrite to use `wake_words: [galileo]` on trigger entries instead of `wake_triggers:` key; assert trigger appears in the `galileo` group
- [x] 7.2 Update `test_wake_triggers_merged_into_wake_words`: same migration — use `wake_words` field
- [x] 7.3 Update `test_user_yaml_wake_triggers_linked`: same migration
- [x] 7.4 Add test: trigger with `wake_words: []` appears in `config.direct_triggers` and not in `config.triggers`
- [x] 7.5 Add test: trigger with `wake_words: [global]` behaves identically to trigger with no `wake_words`
- [x] 7.6 Add test: trigger with `wake_words: [galileo, help]` appears in both group trigger lists

## 8. Validation

- [x] 8.1 Run `uv run pytest tests/test_config.py` — all config tests pass
- [x] 8.2 Run `task fix` — lint clean, full test suite green
