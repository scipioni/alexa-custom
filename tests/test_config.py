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

    def test_null_numeric_fields_fall_back_to_defaults(self, tmp_path):
        """The web config editor can write `key: null` for a cleared field.

        float(None)/int(None) would raise and break cold start, so the parsers
        must treat an explicit null as 'use the default'.
        """
        cfg_path = self._make_config(
            tmp_path,
            "wake_words:\n"
            "  - word: alexa\n"
            "recognition:\n"
            "  matching_threshold: null\n"
            "  command_timeout: null\n"
            "stt:\n"
            "  stage1:\n"
            "    rms_threshold: null\n"
            "    confidence: null\n"
            "audio:\n"
            "  input_gain: null\n",
        )
        from alexa_custom.config import load_config

        result = load_config(cfg_path)  # must not raise
        assert result is not None
        assert result.recognition.matching_threshold == 70.0
        assert result.recognition.command_timeout == 3.0
        assert result.stt.stage1.rms_threshold == pytest.approx(0.02)
        assert result.stt.stage1.confidence == pytest.approx(0.65)
        assert result.audio.input_gain == pytest.approx(1.0)


class TestExampleConfig:
    def test_example_config_loads(self):
        """conf.example/config.yaml must always be loadable — the web dashboard
        serves it as the 'factory defaults'."""
        from alexa_custom.config import load_config

        result = load_config("conf.example/config.yaml")
        assert result is not None
        assert result.wake_words, "example config should define at least one wake word"

    def test_example_config_uses_documented_defaults(self, tmp_path):
        """conf.example/config.yaml should use the documented default values for
        all settings, so it can serve as the true source of defaults and doesn't
        silently drift from the code."""
        from alexa_custom.config import load_config

        # Load the example config to see what it specifies
        example = load_config("conf.example/config.yaml")
        assert example is not None

        # Load a minimal config with only required fields to get dataclass defaults
        minimal_path = write_file(
            tmp_path,
            "minimal.yaml",
            """\
wake_words:
  - word: test
""",
        )
        minimal = load_config(str(minimal_path))
        assert minimal is not None

        # Check that documented numeric and boolean fields match defaults.
        # These are the fields most likely to drift in a copy-paste edit.
        checks = [
            (
                "command_timeout",
                example.recognition.command_timeout,
                minimal.recognition.command_timeout,
            ),
            ("output_volume", example.audio.output_volume, minimal.audio.output_volume),
            ("input_gain", example.audio.input_gain, minimal.audio.input_gain),
        ]
        for field_name, example_val, default_val in checks:
            assert example_val == default_val, (
                f"Example {field_name}={example_val} should match default {default_val}. "
                f"Update conf.example/config.yaml to match the code."
            )


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

<<<<<<< HEAD
=======
    def test_invalid_stage2_backend_raises(self, tmp_path):
        cfg_path = write_file(
            tmp_path,
            "config.yaml",
            "wake_words:\n  - word: alexa\nstt:\n  stage2:\n    backend: invalid\n",
        )
        from alexa_custom.config import load_config, ConfigError

        with pytest.raises(ConfigError, match="stage2.backend"):
            load_config(cfg_path)

    def test_whisper_cpp_stage2_backend(self, tmp_path):
        cfg_path = write_file(
            tmp_path,
            "config.yaml",
            "wake_words:\n  - word: alexa\nstt:\n  stage2:\n    backend: whisper-cpp\n    model_path: models/whisper-cpp/ggml-tiny-q4_0.bin\n",
        )
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result.stt.stage2.backend == "whisper-cpp"
        assert result.stt.stage2.model_path == "models/whisper-cpp/ggml-tiny-q4_0.bin"

    def test_model_variant_defaults_to_auto(self, tmp_path):
        cfg_path = write_file(
            tmp_path,
            "config.yaml",
            "wake_words:\n  - word: alexa\nstt:\n  stage1:\n    backend: sherpa-onnx\n  stage2:\n    backend: sherpa-onnx\n",
        )
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result.stt.stage1.model_variant == "auto"
        assert result.stt.stage2.model_variant == "auto"

    def test_model_variant_zipformer2_ctc(self, tmp_path):
        cfg_path = write_file(
            tmp_path,
            "config.yaml",
            "wake_words:\n  - word: alexa\nstt:\n  stage1:\n    backend: sherpa-onnx\n    model_variant: zipformer2-ctc\n  stage2:\n    backend: sherpa-onnx\n    model_variant: nemo_ctc\n",
        )
        from alexa_custom.config import load_config

        result = load_config(cfg_path)
        assert result.stt.stage1.model_variant == "zipformer2-ctc"
        assert result.stt.stage2.model_variant == "nemo_ctc"

    def test_invalid_model_variant_raises(self, tmp_path):
        cfg_path = write_file(
            tmp_path,
            "config.yaml",
            "wake_words:\n  - word: alexa\nstt:\n  stage1:\n    backend: sherpa-onnx\n    model_variant: invalid\n",
        )
        from alexa_custom.config import load_config, ConfigError

        with pytest.raises(ConfigError, match="model_variant"):
            load_config(cfg_path)

>>>>>>> 84a06b1 (feat: switch sherpa-onnx to NeMo FastConformer CTC with model_variant config)

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

    def test_wake_words_scoped_triggers_merged(self, tmp_path):
        actions_dir = tmp_path / "actions"
        actions_dir.mkdir()
        self._write_system(
            actions_dir,
            "triggers:\n  - phrase: from_system\n    wake_words: [galileo]\n    actions:\n      - type: log\n        message: s\n",
        )
        self._write_file(
            actions_dir,
            "user.yaml",
            "triggers:\n  - phrase: from_user\n    wake_words: [galileo]\n    actions:\n      - type: log\n        message: u\n",
        )
        from alexa_custom.config import _load_actions_dir

        _, data = _load_actions_dir(actions_dir, make_wake_words())
        galileo_triggers = [t for t in data.triggers if t.wake_words == ["galileo"]]
        phrases = [t.phrase for t in galileo_triggers]
        assert "from_system" in phrases
        assert "from_user" in phrases
        assert phrases.index("from_system") < phrases.index("from_user")

    def test_deprecated_wake_triggers_key_ignored(self, tmp_path):
        actions_dir = tmp_path / "actions"
        actions_dir.mkdir()
        self._write_system(
            actions_dir,
            "wake_triggers:\n  nonexistent:\n    - phrase: xyz\n      actions:\n        - type: log\n          message: n\n",
        )
        from alexa_custom.config import _load_actions_dir

        _, data = _load_actions_dir(actions_dir, make_wake_words())
        assert not any(t.phrase == "xyz" for t in data.triggers)

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

    def test_wake_words_scoped_triggers_merged_into_wake_words(self, tmp_path):
        conf_dir = tmp_path / "conf"
        actions_dir = conf_dir / "actions"
        actions_dir.mkdir(parents=True)
        (conf_dir / "config.yaml").write_text(
            "wake_words:\n  - word: galileo\nactions:\n  dir: conf/actions\n"
        )
        (actions_dir / "system.yaml").write_text(
            "triggers:\n  - phrase: che ora è\n    wake_words: [galileo]\n    actions:\n      - type: log\n        message: time\n"
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

    def test_action_file_wake_words_group_and_scoped_trigger(self, tmp_path):
        conf_dir = tmp_path / "conf"
        actions_dir = conf_dir / "actions"
        actions_dir.mkdir(parents=True)
        (conf_dir / "config.yaml").write_text(
            "wake_words:\n  - word: alexa\nactions:\n  dir: conf/actions\n"
        )
        (actions_dir / "user.yaml").write_text(
            "wake_words:\n  - word: aiuto\n    id: help\n"
            "triggers:\n  - phrase: chiama assistenza\n    wake_words: [help]\n    actions:\n      - type: log\n        message: calling\n"
        )
        from alexa_custom.config import load_config

        cfg = load_config(conf_dir / "config.yaml")
        wake_word_ids = {g.id for g in cfg.wake_words}
        assert "help" in wake_word_ids

        help_group = next(g for g in cfg.wake_words if g.id == "help")
        assert any(t.phrase == "chiama assistenza" for t in help_group.triggers)

    def test_direct_trigger_in_direct_triggers_not_global(self, tmp_path):
        conf_dir = tmp_path / "conf"
        actions_dir = conf_dir / "actions"
        actions_dir.mkdir(parents=True)
        (conf_dir / "config.yaml").write_text(
            "wake_words:\n  - word: galileo\nactions:\n  dir: conf/actions\n"
        )
        (actions_dir / "user.yaml").write_text(
            "triggers:\n  - phrase: chiama Stefano\n    wake_words: []\n    actions:\n      - type: log\n        message: x\n"
        )
        from alexa_custom.config import load_config

        cfg = load_config(conf_dir / "config.yaml")
        assert any(t.phrase == "chiama Stefano" for t in cfg.direct_triggers)
        assert not any(t.phrase == "chiama Stefano" for t in cfg.triggers)

    def test_global_explicit_identical_to_absent(self, tmp_path):
        conf_dir = tmp_path / "conf"
        actions_dir = conf_dir / "actions"
        actions_dir.mkdir(parents=True)
        (conf_dir / "config.yaml").write_text(
            "wake_words:\n  - word: galileo\nactions:\n  dir: conf/actions\n"
        )
        (actions_dir / "user.yaml").write_text(
            "triggers:\n"
            "  - phrase: implicit_global\n    actions:\n      - type: log\n        message: x\n"
            "  - phrase: explicit_global\n    wake_words: [global]\n    actions:\n      - type: log\n        message: x\n"
        )
        from alexa_custom.config import load_config

        cfg = load_config(conf_dir / "config.yaml")
        global_phrases = [t.phrase for t in cfg.triggers]
        assert "implicit_global" in global_phrases
        assert "explicit_global" in global_phrases
        assert not any(
            t.phrase in ("implicit_global", "explicit_global")
            for t in cfg.direct_triggers
        )

    def test_multi_wake_word_trigger_appears_in_both_groups(self, tmp_path):
        conf_dir = tmp_path / "conf"
        actions_dir = conf_dir / "actions"
        actions_dir.mkdir(parents=True)
        (conf_dir / "config.yaml").write_text(
            "wake_words:\n  - word: galileo\n    id: galileo\n  - word: aiuto\n    id: help\nactions:\n  dir: conf/actions\n"
        )
        (actions_dir / "user.yaml").write_text(
            "triggers:\n  - phrase: accendi la luce\n    wake_words: [galileo, help]\n    actions:\n      - type: log\n        message: x\n"
        )
        from alexa_custom.config import load_config

        cfg = load_config(conf_dir / "config.yaml")
        galileo_group = next(g for g in cfg.wake_words if g.id == "galileo")
        help_group = next(g for g in cfg.wake_words if g.id == "help")
        assert any(t.phrase == "accendi la luce" for t in galileo_group.triggers)
        assert any(t.phrase == "accendi la luce" for t in help_group.triggers)
        assert not any(t.phrase == "accendi la luce" for t in cfg.triggers)


# ---------------------------------------------------------------------------
# Concurrent file locking tests (web-config-panel task 4.13)
# ---------------------------------------------------------------------------


class TestConcurrentFileLocking:
    def test_exclusive_lock_prevents_simultaneous_writes(self, tmp_path):
        from alexa_custom.web import _file_lock
        import threading

        f = tmp_path / "test.yaml"
        f.write_text("initial\n")

        results = []
        errors = []

        def writer(name: str, content: str):
            try:
                with _file_lock(f, exclusive=True):
                    data = f.read_text()
                    import time

                    time.sleep(0.05)
                    f.write_text(data + content)
                results.append(name)
            except Exception as e:
                errors.append((name, e))

        t1 = threading.Thread(target=writer, args=("A", "write_a\n"))
        t2 = threading.Thread(target=writer, args=("B", "write_b\n"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Unexpected errors: {errors}"
        content = f.read_text()
        assert content.count("write_a") == 1
        assert content.count("write_b") == 1
        assert "write_a" in content
        assert "write_b" in content

    def test_shared_lock_allows_concurrent_reads(self, tmp_path):
        from alexa_custom.web import _file_lock
        import threading

        f = tmp_path / "test.yaml"
        f.write_text("data\n")

        results = []

        def reader(name: str):
            try:
                with _file_lock(f, exclusive=False):
                    _ = f.read_text()
                results.append(name)
            except Exception:
                pass

        threads = [threading.Thread(target=reader, args=(str(i),)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        assert all(r in results for r in ("0", "1", "2", "3", "4"))

    def test_exclusive_lock_blocks_shared_lock(self, tmp_path):
        from alexa_custom.web import _file_lock
        import threading

        f = tmp_path / "test.yaml"
        f.write_text("data\n")
        started = threading.Event()
        proceed = threading.Event()

        exclusive_acquired = threading.Event()
        shared_acquired = threading.Event()
        shared_timed_out = threading.Event()

        def exclusive_holder():
            with _file_lock(f, exclusive=True):
                exclusive_acquired.set()
                proceed.wait(timeout=2)
                started.set()

        def shared_attempt():
            started.wait(timeout=2)
            try:
                with _file_lock(f, exclusive=False):
                    shared_acquired.set()
            except Exception:
                shared_timed_out.set()

        t_ex = threading.Thread(target=exclusive_holder)
        t_sh = threading.Thread(target=shared_attempt)
        t_ex.start()
        exclusive_acquired.wait(timeout=2)
        proceed.set()
        t_sh.start()
        t_sh.join(timeout=1.5)
        t_ex.join()

        assert shared_acquired.is_set()
