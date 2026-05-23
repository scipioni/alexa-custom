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
