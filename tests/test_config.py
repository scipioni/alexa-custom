"""Tests for the new conf/ config architecture."""

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
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def make_conf_dir(tmp_path: Path) -> Path:
    """Create a minimal conf/ directory at tmp_path/conf/ with an actions/ sub-directory."""
    (tmp_path / "conf" / "actions").mkdir(parents=True, exist_ok=True)
    return tmp_path / "conf"


MINIMAL_CONFIG = """\
wake_words:
  - word: alexa
"""

MINIMAL_CONFIG_WITH_RECOGNITION = """\
wake_words:
  - word: alexa
recognition:
  command_timeout: 3.0
"""


# ---------------------------------------------------------------------------
# load_secrets tests (task 10.2)
# ---------------------------------------------------------------------------


class TestLoadSecrets:
    def test_full_secrets_file(self, tmp_path):
        secrets_path = write_file(
            tmp_path,
            "secrets.yaml",
            """\
livekit:
  url: wss://example.livekit.cloud
  api_key: KEY123
  api_secret: SECRET456
  room: my-room
telegram:
  bot_token: "999:TOKEN"
  chat_id: "12345"
llm_host: http://localhost:11434
mqtt:
  username: user
  password: pass
""",
        )
        from alexa_custom.config import load_secrets

        with patch.dict(os.environ, {}, clear=False):
            result = load_secrets(secrets_path)
        assert result.livekit.url == "wss://example.livekit.cloud"
        assert result.livekit.api_key == "KEY123"
        assert result.livekit.api_secret == "SECRET456"
        assert result.livekit.room == "my-room"
        assert result.telegram.bot_token == "999:TOKEN"
        assert result.telegram.chat_id == "12345"
        assert result.llm_host == "http://localhost:11434"
        assert result.mqtt.username == "user"
        assert result.mqtt.password == "pass"

    def test_secrets_applied_to_os_environ(self, tmp_path):
        secrets_path = write_file(
            tmp_path,
            "secrets.yaml",
            """\
livekit:
  url: wss://example.livekit.cloud
  api_key: KEY123
  api_secret: SECRET456
  room: my-room
""",
        )
        from alexa_custom.config import load_secrets

        with patch.dict(os.environ, {}, clear=False):
            load_secrets(secrets_path)
            assert os.environ["LIVEKIT_URL"] == "wss://example.livekit.cloud"
            assert os.environ["LIVEKIT_API_KEY"] == "KEY123"
            assert os.environ["LIVEKIT_ROOM"] == "my-room"

    def test_partial_file_missing_fields_use_defaults(self, tmp_path):
        secrets_path = write_file(
            tmp_path, "secrets.yaml", "livekit:\n  url: wss://example.com\n"
        )
        from alexa_custom.config import load_secrets

        result = load_secrets(secrets_path)
        assert result.livekit.url == "wss://example.com"
        assert result.livekit.api_key == ""
        assert result.telegram.bot_token == ""
        assert result.llm_host is None

    def test_missing_file_returns_empty_config(self, tmp_path):
        from alexa_custom.config import load_secrets

        result = load_secrets(tmp_path / "nonexistent.yaml")
        assert result.livekit.url == ""
        assert result.telegram.bot_token == ""
        assert result.llm_host is None


# ---------------------------------------------------------------------------
# load_config tests
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def _make_config(self, tmp_path: Path, content: str = MINIMAL_CONFIG) -> Path:
        conf = make_conf_dir(tmp_path)
        cfg_path = conf / "config.yaml"
        cfg_path.write_text(content)
        return cfg_path

    def test_config_yaml_not_found_returns_none(self, tmp_path):
        from alexa_custom.config import load_config

        result = load_config(tmp_path / "nonexistent.yaml")
        assert result is None

    def test_malformed_yaml_raises_config_error(self, tmp_path):
        cfg = write_file(tmp_path, "config.yaml", "wake_words: [\nbad yaml")
        from alexa_custom.config import load_config, ConfigError

        with pytest.raises(ConfigError):
            load_config(cfg)

    def test_env_key_raises_config_error(self, tmp_path):
        cfg = write_file(
            tmp_path,
            "config.yaml",
            "env:\n  LIVEKIT_URL: wss://example.com\n" + MINIMAL_CONFIG,
        )
        from alexa_custom.config import load_config, ConfigError

        with pytest.raises(ConfigError, match="env:"):
            load_config(cfg)

    def test_minimal_config_parses(self, tmp_path):
        cfg_path = self._make_config(tmp_path)
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result is not None
        assert [g.word for g in result.wake_words] == ["alexa"]

    def test_nested_recognition_block(self, tmp_path):
        cfg_path = self._make_config(tmp_path, MINIMAL_CONFIG_WITH_RECOGNITION)
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result is not None
        assert result.recognition.command_timeout == 3.0

    def test_nested_audio_block(self, tmp_path):
        cfg_path = self._make_config(
            tmp_path,
            MINIMAL_CONFIG + "audio:\n  output_volume: 0.3\n  card_name: NewPie\n",
        )
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result is not None
        assert result.audio.output_volume == pytest.approx(0.3)
        assert result.audio.card_name == "NewPie"

    def test_nested_stt_block(self, tmp_path):
        cfg_path = self._make_config(
            tmp_path,
            MINIMAL_CONFIG
            + "stt:\n  stage1:\n    backend: vosk\n    confidence: 0.7\n  stage2:\n    backend: vosk\n",
        )
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result is not None
        assert result.stt.stage1.backend == "vosk"
        assert result.stt.stage1.confidence == pytest.approx(0.7)
        assert result.stt.stage2.backend == "vosk"

    def test_wake_word_lang_default(self, tmp_path):
        cfg_path = self._make_config(tmp_path)
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result.wake_words[0].lang == "it-IT"

    def test_wake_word_lang_field(self, tmp_path):
        cfg_path = self._make_config(
            tmp_path, "wake_words:\n  - word: alexa\n    lang: en-US\n"
        )
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result.wake_words[0].lang == "en-US"


# ---------------------------------------------------------------------------
# _parse_stt_config tests (task 10.4)
# ---------------------------------------------------------------------------


class TestParseSttConfig:
    def test_stage1_stage2_independence(self, tmp_path):
        cfg_path = write_file(
            tmp_path,
            "config.yaml",
            """\
wake_words:
  - word: alexa
stt:
  stage1:
    backend: vosk
    confidence: 0.8
    vad_silence_ms: 600
    rms_threshold: 0.03
    min_speech_ms: 400
  stage2:
    backend: sherpa-onnx
    model_path: models/sherpa
""",
        )
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result.stt.stage1.backend == "vosk"
        assert result.stt.stage1.confidence == pytest.approx(0.8)
        assert result.stt.stage1.vad_silence_ms == 600
        assert result.stt.stage1.rms_threshold == pytest.approx(0.03)
        assert result.stt.stage1.min_speech_ms == 400
        assert result.stt.stage2.backend == "sherpa-onnx"
        assert result.stt.stage2.model_path == "models/sherpa"

    def test_stt_defaults(self, tmp_path):
        cfg_path = write_file(tmp_path, "config.yaml", "wake_words:\n  - word: alexa\n")
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result.stt.stage1.backend == "vosk"
        assert result.stt.stage1.confidence == pytest.approx(0.65)
        assert result.stt.stage2.backend == "vosk"

    def test_vad_silence_ms_at_stt_level(self, tmp_path):
        cfg_path = write_file(
            tmp_path,
            "config.yaml",
            "wake_words:\n  - word: alexa\nstt:\n  vad_silence_ms: 800\n",
        )
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result.stt.vad_silence_ms == 800

    def test_keyword_spotter_fields_parsed(self, tmp_path):
        cfg_path = write_file(
            tmp_path,
            "config.yaml",
            "wake_words:\n  - word: galileo\nstt:\n  stage1:\n    backend: sherpa-onnx\n    keyword_spotter: true\n    keywords_score: 1.5\n    keywords_threshold: 0.3\n",
        )
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result.stt.stage1.keyword_spotter is True
        assert result.stt.stage1.keywords_score == pytest.approx(1.5)
        assert result.stt.stage1.keywords_threshold == pytest.approx(0.3)

    def test_keyword_spotter_defaults(self, tmp_path):
        cfg_path = write_file(
            tmp_path, "config.yaml", "wake_words:\n  - word: galileo\n"
        )
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result.stt.stage1.keyword_spotter is False
        assert result.stt.stage1.keywords_score == pytest.approx(1.0)
        assert result.stt.stage1.keywords_threshold == pytest.approx(0.25)

    def test_invalid_stage1_backend_raises(self, tmp_path):
        cfg_path = write_file(
            tmp_path,
            "config.yaml",
            "wake_words:\n  - word: alexa\nstt:\n  stage1:\n    backend: whisper\n",
        )
        from alexa_custom.config import load_config, ConfigError

        with pytest.raises(ConfigError, match="stage1.backend"):
            load_config(cfg_path)


# ---------------------------------------------------------------------------
# _load_actions_dir tests (task 10.3)
# ---------------------------------------------------------------------------


def make_wake_words():
    from alexa_custom.config import WakeWordGroup

    return [WakeWordGroup(word="galileo"), WakeWordGroup(word="alexa")]


class TestLoadActionsDir:
    def _write_system(self, actions_dir: Path, content: str) -> None:
        (actions_dir / "system.yaml").write_text(content)

    def _write_file(self, actions_dir: Path, name: str, content: str) -> None:
        (actions_dir / name).write_text(content)

    def test_system_first_ordering(self, tmp_path):
        actions_dir = tmp_path / "actions"
        actions_dir.mkdir()
        self._write_system(
            actions_dir,
            "triggers:\n  - phrase: system_cmd\n    actions:\n      - type: log\n        message: s\n",
        )
        self._write_file(
            actions_dir,
            "user.yaml",
            "triggers:\n  - phrase: user_cmd\n    actions:\n      - type: log\n        message: u\n",
        )
        from alexa_custom.config import _load_actions_dir

        _, data = _load_actions_dir(actions_dir, make_wake_words())
        phrases = [t.phrase for t in data.triggers]
        assert phrases.index("system_cmd") < phrases.index("user_cmd")

    def test_on_startup_from_system_only(self, tmp_path):
        actions_dir = tmp_path / "actions"
        actions_dir.mkdir()
        self._write_system(
            actions_dir,
            "on_startup:\n  - type: say\n    text: Sistema pronto\n    lang: it-IT\n",
        )
        self._write_file(
            actions_dir,
            "user.yaml",
            "on_startup:\n  - type: say\n    text: Ignored startup\n    lang: it-IT\n",
        )
        from alexa_custom.config import _load_actions_dir

        on_startup, _ = _load_actions_dir(actions_dir, make_wake_words())
        assert len(on_startup) == 1
        assert on_startup[0].params.get("text") == "Sistema pronto"

    def test_wake_triggers_merged(self, tmp_path):
        actions_dir = tmp_path / "actions"
        actions_dir.mkdir()
        self._write_system(
            actions_dir,
            "wake_triggers:\n  galileo:\n    - phrase: from_system\n      actions:\n        - type: log\n          message: s\n",
        )
        self._write_file(
            actions_dir,
            "user.yaml",
            "wake_triggers:\n  galileo:\n    - phrase: from_user\n      actions:\n        - type: log\n          message: u\n",
        )
        from alexa_custom.config import _load_actions_dir

        _, data = _load_actions_dir(actions_dir, make_wake_words())
        phrases = [t.phrase for t in data.wake_triggers.get("galileo", [])]
        assert "from_system" in phrases
        assert "from_user" in phrases
        assert phrases.index("from_system") < phrases.index("from_user")

    def test_unknown_wake_word_ignored(self, tmp_path):
        actions_dir = tmp_path / "actions"
        actions_dir.mkdir()
        self._write_system(
            actions_dir,
            "wake_triggers:\n  nonexistent:\n    - phrase: xyz\n      actions:\n        - type: log\n          message: n\n",
        )
        from alexa_custom.config import _load_actions_dir

        _, data = _load_actions_dir(actions_dir, make_wake_words())
        assert "nonexistent" not in data.wake_triggers

    def test_multiple_files_alphabetical_after_system(self, tmp_path):
        actions_dir = tmp_path / "actions"
        actions_dir.mkdir()
        self._write_system(
            actions_dir,
            "triggers:\n  - phrase: s\n    actions:\n      - type: log\n        message: x\n",
        )
        self._write_file(
            actions_dir,
            "home.yaml",
            "triggers:\n  - phrase: h\n    actions:\n      - type: log\n        message: x\n",
        )
        self._write_file(
            actions_dir,
            "learned.yaml",
            "triggers:\n  - phrase: l\n    actions:\n      - type: log\n        message: x\n",
        )
        self._write_file(
            actions_dir,
            "user.yaml",
            "triggers:\n  - phrase: u\n    actions:\n      - type: log\n        message: x\n",
        )
        from alexa_custom.config import _load_actions_dir

        _, data = _load_actions_dir(actions_dir, make_wake_words())
        phrases = [t.phrase for t in data.triggers]
        assert phrases == ["s", "h", "l", "u"]

    def test_non_yaml_files_ignored(self, tmp_path):
        actions_dir = tmp_path / "actions"
        actions_dir.mkdir()
        (actions_dir / "notes.txt").write_text("not yaml")
        self._write_system(
            actions_dir,
            "triggers:\n  - phrase: sys\n    actions:\n      - type: log\n        message: x\n",
        )
        from alexa_custom.config import _load_actions_dir

        _, data = _load_actions_dir(actions_dir, make_wake_words())
        assert data.triggers[0].phrase == "sys"
        assert len(data.triggers) == 1

    def test_empty_directory_returns_empty_data(self, tmp_path):
        actions_dir = tmp_path / "actions"
        actions_dir.mkdir()
        from alexa_custom.config import _load_actions_dir

        on_startup, data = _load_actions_dir(actions_dir, make_wake_words())
        assert on_startup == []
        assert data.triggers == []


# ---------------------------------------------------------------------------
# LLM config tests
# ---------------------------------------------------------------------------


class TestLLMConfig:
    def test_llm_config_parsed_with_inline_host(self, tmp_path):
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

    def test_llm_invalid_backend_disables_llm(self, tmp_path):
        p = write_file(
            tmp_path,
            "config.yaml",
            """\
wake_words:
  - word: alexa
llm:
  backend: unsupported_backend
  host: http://localhost
  model: some-model
""",
        )
        from alexa_custom.config import load_config

        cfg = load_config(p)
        assert cfg is not None
        assert cfg.llm is None

    def test_llm_openai_backend_loads(self, tmp_path):
        p = write_file(
            tmp_path,
            "config.yaml",
            """\
wake_words:
  - word: alexa
llm:
  backend: openai
  host: https://api.openai.com
  model: gpt-4o
  api_key: sk-test
""",
        )
        from alexa_custom.config import load_config

        cfg = load_config(p)
        assert cfg is not None
        assert cfg.llm is not None
        assert cfg.llm.backend == "openai"
        assert cfg.llm.api_key == "sk-test"

    def test_llm_absent_gives_none(self, tmp_path):
        p = write_file(tmp_path, "config.yaml", "wake_words:\n  - word: alexa\n")
        from alexa_custom.config import load_config

        cfg = load_config(p)
        assert cfg.llm is None


# ---------------------------------------------------------------------------
# ConfigManager tests
# ---------------------------------------------------------------------------


class TestConfigManager:
    def _make_config(self, tmp_path: Path, wake_words=None) -> Path:
        words = wake_words or ["alexa"]
        entries = "\n".join(f"  - word: {w}" for w in words)
        p = tmp_path / "config.yaml"
        p.write_text(f"wake_words:\n{entries}\n")
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

        cfg_path.write_text("wake_words:\n  - word: computer\n")
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
        await asyncio.sleep(0.05)

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

        cfg_path.write_text("wake_words:\n  - word: computer\n")
        import time

        time.sleep(0.01)

        await asyncio.sleep(0.2)
        mgr.stop_watcher()
        await asyncio.sleep(0.05)

        assert received and received[-1] == ["computer"]


# ---------------------------------------------------------------------------
# env: key raises ConfigError (task 10.5)
# ---------------------------------------------------------------------------


class TestEnvKeyRejected:
    def test_env_key_raises_config_error(self, tmp_path):
        cfg = write_file(
            tmp_path,
            "config.yaml",
            "env:\n  LIVEKIT_URL: wss://example.com\nwake_words:\n  - word: alexa\n",
        )
        from alexa_custom.config import load_config, ConfigError

        with pytest.raises(ConfigError, match="env:"):
            load_config(cfg)

    def test_config_without_env_section_parses(self, tmp_path):
        cfg = write_file(tmp_path, "config.yaml", "wake_words:\n  - word: alexa\n")
        from alexa_custom.config import load_config

        result = load_config(cfg)
        assert result is not None
        assert [g.word for g in result.wake_words] == ["alexa"]


# ---------------------------------------------------------------------------
# Action files integration via load_config
# ---------------------------------------------------------------------------


class TestActionsDirectoryIntegration:
    def test_triggers_loaded_from_actions_dir(self, tmp_path):
        conf_dir = tmp_path / "conf"
        actions_dir = conf_dir / "actions"
        actions_dir.mkdir(parents=True)
        (conf_dir / "config.yaml").write_text(
            "wake_words:\n  - word: alexa\nactions:\n  dir: conf/actions\n"
        )
        (actions_dir / "system.yaml").write_text(
            "triggers:\n  - phrase: system trigger\n    actions:\n      - type: log\n        message: ok\n"
        )
        from alexa_custom.config import load_config

        cfg = load_config(conf_dir / "config.yaml")
        assert cfg is not None
        phrases = [t.phrase for t in cfg.triggers]
        assert "system trigger" in phrases

    def test_on_startup_loaded_from_system_yaml(self, tmp_path):
        conf_dir = tmp_path / "conf"
        actions_dir = conf_dir / "actions"
        actions_dir.mkdir(parents=True)
        (conf_dir / "config.yaml").write_text(
            "wake_words:\n  - word: alexa\nactions:\n  dir: conf/actions\n"
        )
        (actions_dir / "system.yaml").write_text(
            "on_startup:\n  - type: say\n    text: Ciao\n    lang: it-IT\n"
        )
        from alexa_custom.config import load_config

        cfg = load_config(conf_dir / "config.yaml")
        assert len(cfg.on_startup) == 1
        assert cfg.on_startup[0].params.get("text") == "Ciao"

    def test_wake_triggers_merged_into_wake_words(self, tmp_path):
        conf_dir = tmp_path / "conf"
        actions_dir = conf_dir / "actions"
        actions_dir.mkdir(parents=True)
        (conf_dir / "config.yaml").write_text(
            "wake_words:\n  - word: galileo\nactions:\n  dir: conf/actions\n"
        )
        (actions_dir / "system.yaml").write_text(
            "wake_triggers:\n  galileo:\n    - phrase: che ora è\n      actions:\n        - type: log\n          message: time\n"
        )
        from alexa_custom.config import load_config

        cfg = load_config(conf_dir / "config.yaml")
        galileo_group = cfg.wake_words[0]
        assert any(t.phrase == "che ora è" for t in galileo_group.triggers)

    @pytest.mark.asyncio
    async def test_action_file_change_triggers_reload(self, tmp_path):
        conf_dir = tmp_path / "conf"
        actions_dir = conf_dir / "actions"
        actions_dir.mkdir(parents=True)
        cfg_path = conf_dir / "config.yaml"
        cfg_path.write_text(
            "wake_words:\n  - word: alexa\nactions:\n  dir: conf/actions\n"
        )
        system_path = actions_dir / "system.yaml"
        system_path.write_text(
            "triggers:\n  - phrase: old_cmd\n    actions:\n      - type: log\n        message: x\n"
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

        system_path.write_text(
            "triggers:\n  - phrase: new_cmd\n    actions:\n      - type: log\n        message: x\n"
        )
        time.sleep(0.01)

        await asyncio.sleep(0.3)
        mgr.stop_watcher()
        await asyncio.sleep(0.05)

        assert received and "new_cmd" in received[-1]
