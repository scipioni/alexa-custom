"""Tests for config loading (config.yaml with env: section and fallback behavior)."""

from __future__ import annotations

import os
import pytest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_file(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


MINIMAL_ACTIONS = """\
wake_words:
  - word: alexa
command_timeout: 3.0
triggers:
  - phrase: "chiama"
    actions:
      - type: log
        message: "calling"
"""


# ---------------------------------------------------------------------------
# load_config tests (task 1.1)
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_env_section_writes_to_os_environ(self, tmp_path):
        cfg = write_file(
            tmp_path,
            "config.yaml",
            "env:\n  LIVEKIT_URL: wss://example.com\n  MY_SECRET: supersecret\n"
            + MINIMAL_ACTIONS,
        )
        from alexa_custom.config import load_config

        with patch.dict(os.environ, {}, clear=False):
            result = load_config(cfg)
            assert os.environ["LIVEKIT_URL"] == "wss://example.com"
            assert os.environ["MY_SECRET"] == "supersecret"
        assert result is not None
        assert [g.word for g in result.wake_words] == ["alexa"]

    def test_env_section_overwrites_existing_env(self, tmp_path):
        cfg = write_file(
            tmp_path,
            "config.yaml",
            "env:\n  TELEGRAM_BOT_TOKEN: new_token\n" + MINIMAL_ACTIONS,
        )
        from alexa_custom.config import load_config

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "old_token"}):
            load_config(cfg)
            assert os.environ["TELEGRAM_BOT_TOKEN"] == "new_token"

    def test_config_without_env_section_parses_actions(self, tmp_path):
        cfg = write_file(tmp_path, "config.yaml", MINIMAL_ACTIONS)
        from alexa_custom.config import load_config

        result = load_config(cfg)
        assert result is not None
        assert len(result.triggers) == 1
        assert result.triggers[0].phrase == "chiama"

    def test_config_yaml_not_found_returns_none(self, tmp_path):
        from alexa_custom.config import load_config

        result = load_config(tmp_path / "nonexistent.yaml")
        assert result is None

    def test_malformed_yaml_raises_config_error(self, tmp_path):
        cfg = write_file(tmp_path, "config.yaml", "wake_words: [\nbad yaml")
        from alexa_custom.config import load_config, ConfigError

        with pytest.raises(ConfigError):
            load_config(cfg)

    def test_env_values_are_strings(self, tmp_path):
        cfg = write_file(
            tmp_path, "config.yaml", "env:\n  MQTT_PORT: 1883\n" + MINIMAL_ACTIONS
        )
        from alexa_custom.config import load_config

        load_config(cfg)
        assert os.environ["MQTT_PORT"] == "1883"


# ---------------------------------------------------------------------------
# ConfigManager tests (tasks 2.1–2.7)
# ---------------------------------------------------------------------------


class TestConfigManager:
    def _make_config(self, tmp_path: Path, wake_words=None) -> Path:
        words = wake_words or ["alexa"]
        entries = "\n".join(f"  - word: {w}" for w in words)
        p = tmp_path / "config.yaml"
        p.write_text(f"wake_words:\n{entries}\ntriggers: []\n")
        return p

    def test_holds_initial_config(self, tmp_path):
        cfg_path = self._make_config(tmp_path)
        from alexa_custom.config import load_config
        from alexa_custom.config_manager import ConfigManager

        config = load_config(cfg_path)
        mgr = ConfigManager(config)
        assert mgr.config is config

    def test_register_reload_callback_called_on_reload(self, tmp_path):
        cfg_path = self._make_config(tmp_path)
        from alexa_custom.config import load_config
        from alexa_custom.config_manager import ConfigManager

        initial = load_config(cfg_path)
        mgr = ConfigManager(initial)

        received = []
        mgr.register_reload_callback(lambda c: received.append(c))

        # Overwrite file with new content
        cfg_path.write_text("wake_words:\n  - word: computer\ntriggers: []\n")
        mgr._reload(cfg_path)

        assert len(received) == 1
        assert [g.word for g in received[0].wake_words] == ["computer"]

    def test_malformed_yaml_keeps_previous_config(self, tmp_path):
        cfg_path = self._make_config(tmp_path)
        from alexa_custom.config import load_config
        from alexa_custom.config_manager import ConfigManager

        initial = load_config(cfg_path)
        mgr = ConfigManager(initial)

        called = []
        mgr.register_reload_callback(lambda c: called.append(c))

        cfg_path.write_text("wake_words: [\nbad yaml")
        mgr._reload(cfg_path)

        assert mgr.config is initial
        assert called == []

    @pytest.mark.asyncio
    async def test_watcher_cancels_cleanly(self, tmp_path):
        cfg_path = self._make_config(tmp_path)
        from alexa_custom.config import load_config
        from alexa_custom.config_manager import ConfigManager
        import asyncio

        config = load_config(cfg_path)
        mgr = ConfigManager(config)
        mgr.start_watcher(cfg_path, interval=0.05)
        await asyncio.sleep(0.1)
        mgr.stop_watcher()
        # Give event loop a tick to process cancellation
        await asyncio.sleep(0.05)
        # No unhandled exception = pass

    @pytest.mark.asyncio
    async def test_watcher_detects_file_change_and_reloads(self, tmp_path):
        cfg_path = self._make_config(tmp_path)
        from alexa_custom.config import load_config
        from alexa_custom.config_manager import ConfigManager
        import asyncio

        config = load_config(cfg_path)
        mgr = ConfigManager(config)

        received = []
        mgr.register_reload_callback(
            lambda c: received.append([g.word for g in c.wake_words])
        )

        mgr.start_watcher(cfg_path, interval=0.05)
        await asyncio.sleep(0.05)

        # Modify file (force mtime change)
        cfg_path.write_text("wake_words:\n  - word: computer\ntriggers: []\n")
        import time

        time.sleep(0.01)  # ensure mtime differs

        await asyncio.sleep(0.2)  # wait for watcher tick
        mgr.stop_watcher()
        await asyncio.sleep(0.05)

        assert received and received[-1] == ["computer"]

    def test_reload_logs_keys_not_values(self, tmp_path, caplog):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "env:\n  SECRET_KEY: topsecret\nwake_words:\n  - word: alexa\ntriggers: []\n"
        )
        from alexa_custom.config import load_config
        from alexa_custom.config_manager import ConfigManager
        import logging

        initial = load_config(cfg_path)
        mgr = ConfigManager(initial)

        cfg_path.write_text(
            "env:\n  SECRET_KEY: newsecret\nwake_words:\n  - word: alexa\ntriggers: []\n"
        )
        with caplog.at_level(logging.DEBUG, logger="alexa_custom.config_manager"):
            with caplog.at_level(logging.DEBUG, logger="alexa_custom.config"):
                mgr._reload(cfg_path)

        log_text = " ".join(r.message for r in caplog.records)
        assert "newsecret" not in log_text
        assert "topsecret" not in log_text


# ---------------------------------------------------------------------------
# LLM config, lang, actions_file tests (task 10.1)
# ---------------------------------------------------------------------------


class TestLLMConfig:
    def test_llm_config_parsed(self, tmp_path):
        p = write_file(
            tmp_path,
            "config.yaml",
            """\
wake_words:
  - word: alexa
llm:
  backend: ollama
  host: http://192.168.1.10:11434
  model: llama3.2
""",
        )
        from alexa_custom.config import load_config

        cfg = load_config(p)
        assert cfg.llm is not None
        assert cfg.llm.host == "http://192.168.1.10:11434"
        assert cfg.llm.model == "llama3.2"
        assert cfg.llm.context_turns == 10
        assert cfg.llm.fallback_on_no_match is False

    def test_llm_invalid_backend_raises(self, tmp_path):
        p = write_file(
            tmp_path,
            "config.yaml",
            """\
wake_words:
  - word: alexa
llm:
  backend: openai
  host: http://localhost
  model: gpt-4
""",
        )
        from alexa_custom.config import load_config, ConfigError

        with pytest.raises(ConfigError, match="ollama"):
            load_config(p)

    def test_llm_absent_gives_none(self, tmp_path):
        p = write_file(tmp_path, "config.yaml", "wake_words:\n  - word: alexa\n")
        from alexa_custom.config import load_config

        cfg = load_config(p)
        assert cfg.llm is None

    def test_wake_word_lang_field(self, tmp_path):
        p = write_file(
            tmp_path,
            "config.yaml",
            """\
wake_words:
  - word: alexa
    lang: en-US
""",
        )
        from alexa_custom.config import load_config

        cfg = load_config(p)
        assert cfg.wake_words[0].lang == "en-US"

    def test_wake_word_lang_default(self, tmp_path):
        p = write_file(tmp_path, "config.yaml", "wake_words:\n  - word: alexa\n")
        from alexa_custom.config import load_config

        cfg = load_config(p)
        assert cfg.wake_words[0].lang == "it-IT"


class TestActionsFileMerge:
    def test_global_triggers_merged(self, tmp_path):
        write_file(
            tmp_path,
            "actions.yaml",
            """\
triggers:
  - phrase: "learned trigger"
    actions:
      - type: log
        message: ok
""",
        )
        p = write_file(
            tmp_path,
            "config.yaml",
            """\
wake_words:
  - word: alexa
actions_file: actions.yaml
""",
        )
        from alexa_custom.config import load_config

        cfg = load_config(p)
        phrases = [t.phrase for t in cfg.triggers]
        assert "learned trigger" in phrases

    def test_wake_triggers_merged_into_group(self, tmp_path):
        write_file(
            tmp_path,
            "actions.yaml",
            """\
wake_triggers:
  alexa:
    - phrase: "comando specifico"
      actions:
        - type: log
          message: ok
""",
        )
        p = write_file(
            tmp_path,
            "config.yaml",
            """\
wake_words:
  - word: alexa
actions_file: actions.yaml
""",
        )
        from alexa_custom.config import load_config

        cfg = load_config(p)
        grp = cfg.wake_words[0]
        phrases = [t.phrase for t in grp.triggers]
        assert "comando specifico" in phrases

    def test_unknown_wake_word_key_ignored(self, tmp_path):
        write_file(
            tmp_path,
            "actions.yaml",
            """\
wake_triggers:
  unknown_word:
    - phrase: "xyz"
      actions:
        - type: log
          message: ok
""",
        )
        p = write_file(
            tmp_path,
            "config.yaml",
            """\
wake_words:
  - word: alexa
actions_file: actions.yaml
""",
        )
        from alexa_custom.config import load_config

        cfg = load_config(p)  # should not raise
        assert len(cfg.wake_words[0].triggers) == 0

    def test_missing_actions_file_logs_warning(self, tmp_path, caplog):
        p = write_file(
            tmp_path,
            "config.yaml",
            """\
wake_words:
  - word: alexa
actions_file: nonexistent.yaml
""",
        )
        from alexa_custom.config import load_config
        import logging

        with caplog.at_level(logging.WARNING, logger="alexa_custom.config"):
            cfg = load_config(p)
        assert cfg is not None
        assert any("nonexistent" in r.message for r in caplog.records)


class TestActionsFileHotReload:
    @pytest.mark.asyncio
    async def test_actions_yaml_change_triggers_reload(self, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        af_path = tmp_path / "actions.yaml"
        af_path.write_text(
            "triggers:\n  - phrase: old\n    actions:\n      - type: log\n        message: x\n"
        )
        cfg_path.write_text(
            "wake_words:\n  - word: alexa\nactions_file: actions.yaml\n"
        )
        from alexa_custom.config import load_config
        from alexa_custom.config_manager import ConfigManager
        import asyncio
        import time

        config = load_config(cfg_path)
        mgr = ConfigManager(config)

        received = []
        mgr.register_reload_callback(
            lambda c: received.append([t.phrase for t in c.triggers])
        )

        mgr.start_watcher(cfg_path, interval=0.05)
        await asyncio.sleep(0.05)

        # Modify only actions.yaml
        af_path.write_text(
            "triggers:\n  - phrase: new_learned\n    actions:\n      - type: log\n        message: x\n"
        )
        time.sleep(0.01)

        await asyncio.sleep(0.3)
        mgr.stop_watcher()
        await asyncio.sleep(0.05)

        assert received and "new_learned" in received[-1]
