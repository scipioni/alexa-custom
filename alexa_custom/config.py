from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class ConfigError(ValueError):
    pass


@dataclass
class ActionEntry:
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    on_reply: list[Trigger] = field(default_factory=list)
    on_else: list[ActionEntry] = field(default_factory=list)


@dataclass
class Trigger:
    phrase: str
    actions: list[ActionEntry]
    aliases: list[str] = field(default_factory=list)


@dataclass
class WakeWordGroup:
    word: str
    aliases: list[str] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    lang: str = "it-IT"


_DEFAULT_EXIT_PHRASES = [
    "stop",
    "esci",
    "basta",
    "fine",
    "fermati",
    "chiudi",
    "exit",
    "quit",
    "annulla",
    "cancella",
]


@dataclass
class LLMConfig:
    backend: str
    host: str
    model: str = "ssfdre38/gemma4-nano"
    context_turns: int = 10
    context_window_secs: int = 60
    fallback_on_no_match: bool = True
    learn_commands: bool = True
    system_prompt: str | None = None
    request_timeout: float = 60.0
    exit_phrases: list[str] = field(default_factory=lambda: list(_DEFAULT_EXIT_PHRASES))


_VALID_MODES = {"two-stage", "single-stage"}


@dataclass
class ActionsConfig:
    wake_words: list[WakeWordGroup]
    command_timeout: float
    triggers: list[Trigger]  # global fallback; may be empty
    on_startup: list[ActionEntry] = field(default_factory=list)
    recognition_mode: str = "two-stage"
    wake_confidence: float = 0.75
    wake_tone: str = "wake"
    tts_preroll_ms: int = 400
    tts_backend: str = "piper"
    tts_voice: str = "it_IT-paola-medium"
    stt_backend: str = "vosk"
    stt_model_path: str | None = None
    output_volume: float = 0.5
    input_gain: float = 1.0
    # Audio hardware
    audio_card_name: str = "NewPie"
    audio_sample_rates: dict = field(
        default_factory=lambda: {"usb": 48000, "bluetooth": 16000, "internal": 48000}
    )
    audio_post_playback_ms: int = 100
    audio_tone_preroll_ms: int = 300
    audio_mic_gain: int = 300
    # Connection timing
    reconnect_delay: int = 5
    # MQTT
    mqtt_queue_max: int = 200
    # STT thresholds
    stt_vad_silence_ms: int = 700
    stt_stage1_vad_silence_ms: int = 500
    stt_stage1_rms_threshold: float = 0.02
    # Config watcher
    config_poll_interval: int = 2
    # External actions file
    actions_file: str | None = None
    # LLM
    llm: LLMConfig | None = None


@dataclass
class ActionsData:
    triggers: list[Trigger] = field(default_factory=list)
    wake_triggers: dict[str, list[Trigger]] = field(default_factory=dict)


def _parse_actions(raw_actions: list[Any], path_prefix: str) -> list[ActionEntry]:
    actions: list[ActionEntry] = []
    for i, a in enumerate(raw_actions):
        if not isinstance(a, dict):
            raise ConfigError(f"config:{path_prefix}.actions[{i}] must be a mapping")
        action_type = a.get("type")
        if not action_type or not isinstance(action_type, str):
            raise ConfigError(
                f"config:{path_prefix}.actions[{i}] missing 'type' string"
            )

        on_reply: list[Trigger] = []
        raw_reply = a.get("on_reply")
        if raw_reply is not None:
            if not isinstance(raw_reply, list):
                raise ConfigError(
                    f"config:{path_prefix}.actions[{i}].on_reply must be a list"
                )
            on_reply = _parse_triggers(
                raw_reply, f"{path_prefix}.actions[{i}].on_reply"
            )

        on_else: list[ActionEntry] = []
        raw_else = a.get("on_else")
        if raw_else is not None:
            if not isinstance(raw_else, list):
                raise ConfigError(
                    f"config:{path_prefix}.actions[{i}].on_else must be a list"
                )
            on_else = _parse_actions(raw_else, f"{path_prefix}.actions[{i}].on_else")

        params = {
            k: v for k, v in a.items() if k not in ("type", "on_reply", "on_else")
        }
        actions.append(
            ActionEntry(
                type=action_type, params=params, on_reply=on_reply, on_else=on_else
            )
        )
    return actions


def _parse_triggers(raw_triggers: list[Any], path_prefix: str) -> list[Trigger]:
    triggers: list[Trigger] = []
    for i, t in enumerate(raw_triggers):
        if not isinstance(t, dict):
            raise ConfigError(f"config:{path_prefix}[{i}] must be a mapping")
        phrase = t.get("phrase")
        if not phrase or not isinstance(phrase, str):
            raise ConfigError(f"config:{path_prefix}[{i}] missing 'phrase' string")
        raw_actions = t.get("actions")
        if not isinstance(raw_actions, list):
            raise ConfigError(f"config:{path_prefix}[{i}] 'actions' must be a list")

        actions = _parse_actions(raw_actions, f"{path_prefix}[{i}]")
        raw_aliases = t.get("aliases", [])
        if not isinstance(raw_aliases, list):
            raise ConfigError(f"config:{path_prefix}[{i}].aliases must be a list")
        aliases = [str(a) for a in raw_aliases if a]
        triggers.append(Trigger(phrase=phrase, actions=actions, aliases=aliases))
    return triggers


def _parse_wake_word_groups(raw_groups: list[Any], source: str) -> list[WakeWordGroup]:
    groups: list[WakeWordGroup] = []
    seen: dict[str, int] = {}  # normalized phrase → group index for duplicate detection

    for i, entry in enumerate(raw_groups):
        if not isinstance(entry, dict):
            raise ConfigError(
                f"{source}: wake_words[{i}] must be a mapping with a 'word' key — "
                f"got {type(entry).__name__!r}. Use: '- word: {entry}'"
            )
        word = entry.get("word")
        if not word or not isinstance(word, str):
            raise ConfigError(
                f"{source}: wake_words[{i}] missing required 'word' string"
            )

        raw_aliases = entry.get("aliases", [])
        if not isinstance(raw_aliases, list):
            raise ConfigError(f"{source}: wake_words[{i}].aliases must be a list")
        aliases = [str(a) for a in raw_aliases]

        raw_group_triggers = entry.get("triggers")
        if raw_group_triggers is not None:
            if not isinstance(raw_group_triggers, list):
                raise ConfigError(f"{source}: wake_words[{i}].triggers must be a list")
            group_triggers = _parse_triggers(
                raw_group_triggers, f"wake_words[{i}].triggers"
            )
        else:
            group_triggers = []

        for phrase in [word] + aliases:
            norm = phrase.lower().strip()
            if norm in seen:
                logger.warning(
                    "%s: wake phrase %r also defined in group %d — group %d will shadow it",
                    source,
                    phrase,
                    seen[norm],
                    i,
                )
            else:
                seen[norm] = i

        lang = str(entry.get("lang", "it-IT"))

        groups.append(
            WakeWordGroup(
                word=word, aliases=aliases, triggers=group_triggers, lang=lang
            )
        )

    return groups


def _parse_actions_file(path: Path) -> ActionsData:
    """Parse an actions.yaml file into an ActionsData (global triggers + wake_triggers map)."""
    try:
        with path.open() as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"actions.yaml parse error: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError("actions.yaml must be a YAML mapping at the top level")

    triggers: list[Trigger] = []
    raw_triggers = raw.get("triggers")
    if raw_triggers is not None:
        if not isinstance(raw_triggers, list):
            raise ConfigError("actions.yaml: 'triggers' must be a list if present")
        triggers = _parse_triggers(raw_triggers, "actions.yaml:triggers")

    wake_triggers: dict[str, list[Trigger]] = {}
    raw_wake = raw.get("wake_triggers")
    if raw_wake is not None:
        if not isinstance(raw_wake, dict):
            raise ConfigError(
                "actions.yaml: 'wake_triggers' must be a mapping if present"
            )
        for word, raw_wt in raw_wake.items():
            if not isinstance(raw_wt, list):
                raise ConfigError(
                    f"actions.yaml: 'wake_triggers.{word}' must be a list"
                )
            wake_triggers[str(word)] = _parse_triggers(
                raw_wt, f"actions.yaml:wake_triggers.{word}"
            )

    return ActionsData(triggers=triggers, wake_triggers=wake_triggers)


def _parse_llm_config(raw_llm: dict, source: str) -> LLMConfig:
    backend = str(raw_llm.get("backend", ""))
    if backend != "ollama":
        raise ConfigError(f"{source}: 'llm.backend' must be 'ollama', got {backend!r}")
    host = raw_llm.get("host")
    if not host or not isinstance(host, str):
        raise ConfigError(f"{source}: 'llm.host' is required")
    model = raw_llm.get("model")
    if not model or not isinstance(model, str):
        raise ConfigError(f"{source}: 'llm.model' is required")
    raw_exit = raw_llm.get("exit_phrases")
    exit_phrases = (
        [str(p) for p in raw_exit if p]
        if isinstance(raw_exit, list)
        else list(_DEFAULT_EXIT_PHRASES)
    )
    return LLMConfig(
        backend=backend,
        host=host,
        model=model,
        context_turns=int(raw_llm.get("context_turns", 10)),
        context_window_secs=int(raw_llm.get("context_window_secs", 60)),
        fallback_on_no_match=bool(raw_llm.get("fallback_on_no_match", True)),
        learn_commands=bool(raw_llm.get("learn_commands", True)),
        system_prompt=raw_llm.get("system_prompt") or None,
        request_timeout=float(raw_llm.get("request_timeout", 60.0)),
        exit_phrases=exit_phrases,
    )


def load_config(path: str | Path) -> ActionsConfig | None:
    """Load config.yaml, apply env: section to os.environ, parse actions schema."""
    p = Path(path)
    if not p.exists():
        return None

    try:
        with p.open() as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"config.yaml parse error: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError("config.yaml must be a YAML mapping at the top level")

    # Apply env: section into os.environ (overwrites existing values)
    env_section = raw.pop("env", None)
    applied_env_keys: list[str] = []
    if env_section is not None:
        if not isinstance(env_section, dict):
            raise ConfigError("config.yaml: 'env' must be a mapping")
        for k, v in env_section.items():
            os.environ[str(k)] = str(v)
            applied_env_keys.append(str(k))
    if applied_env_keys:
        logger.debug("Applied env keys from config: %s", ", ".join(applied_env_keys))

    config = _parse_actions_config(raw, source=str(p))

    # Merge actions.yaml when actions_file is configured
    if config.actions_file:
        af_path = Path(config.actions_file)
        if not af_path.is_absolute():
            af_path = p.parent / af_path
        if af_path.exists():
            actions_data = _parse_actions_file(af_path)
            config.triggers = config.triggers + actions_data.triggers
            word_map = {g.word: g for g in config.wake_words}
            for word, wt_triggers in actions_data.wake_triggers.items():
                if word in word_map:
                    word_map[word].triggers = word_map[word].triggers + wt_triggers
                else:
                    logger.debug(
                        "actions.yaml: wake_triggers key %r has no matching wake word group — ignored",
                        word,
                    )
        else:
            logger.warning("actions_file %r not found — skipping", str(af_path))
    else:
        # Suggest actions_file if actions.yaml exists alongside config and learn_commands is on
        implicit_af = p.parent / "actions.yaml"
        if implicit_af.exists() and config.llm and config.llm.learn_commands:
            logger.info(
                "actions.yaml found alongside config.yaml — consider adding "
                "'actions_file: actions.yaml' to config.yaml so the learning agent can update it"
            )

    return config


def _parse_actions_config(raw: dict, source: str = "config") -> ActionsConfig:
    """Parse a raw YAML dict (env: already stripped) into ActionsConfig."""
    raw_wake_words = raw.get("wake_words")
    if (
        not raw_wake_words
        or not isinstance(raw_wake_words, list)
        or len(raw_wake_words) == 0
    ):
        raise ConfigError(f"{source}: 'wake_words' must be a non-empty list")

    wake_words = _parse_wake_word_groups(raw_wake_words, source)

    command_timeout = float(raw.get("command_timeout", 3.0))

    recognition_mode = str(raw.get("recognition_mode", "two-stage"))
    if recognition_mode not in _VALID_MODES:
        raise ConfigError(
            f"{source}: 'recognition_mode' must be one of {sorted(_VALID_MODES)}, got {recognition_mode!r}"
        )

    wake_confidence = float(raw.get("wake_confidence", 0.75))
    wake_tone = str(raw.get("wake_tone", "wake"))

    # A `tts:` block, when present, overrides top-level keys. Both shapes are
    # supported so existing configs keep working:
    #     tts_preroll_ms: 400
    # or
    #     tts:
    #       backend: piper
    #       voice: it_IT-paola-medium
    #       preroll_ms: 400
    tts_section = raw.get("tts") or {}
    if not isinstance(tts_section, dict):
        raise ConfigError(f"{source}: 'tts' must be a mapping if present")

    tts_preroll_ms = int(tts_section.get("preroll_ms", raw.get("tts_preroll_ms", 400)))
    tts_backend = str(tts_section.get("backend", raw.get("tts_backend", "piper")))
    tts_voice = str(
        tts_section.get("voice", raw.get("tts_voice", "it_IT-paola-medium"))
    )

    stt_section = raw.get("stt") or {}
    if not isinstance(stt_section, dict):
        raise ConfigError(f"{source}: 'stt' must be a mapping if present")

    stt_backend = str(stt_section.get("backend", raw.get("stt_backend", "vosk")))
    if stt_backend not in ("vosk", "sherpa-onnx"):
        raise ConfigError(
            f"{source}: 'stt.backend' must be 'vosk' or 'sherpa-onnx', got {stt_backend!r}"
        )

    stt_model_path_raw = stt_section.get("model_path") or raw.get("stt_model_path")
    stt_model_path: str | None = None
    if stt_model_path_raw is not None:
        if not isinstance(stt_model_path_raw, str):
            raise ConfigError(f"{source}: 'stt.model_path' must be a string if present")
        stt_model_path = stt_model_path_raw

    output_volume = float(raw.get("output_volume", 0.5))
    if not (0.0 <= output_volume <= 1.0):
        raise ConfigError(
            f"{source}: 'output_volume' must be between 0.0 and 1.0, got {output_volume}"
        )

    input_gain = float(raw.get("input_gain", 1.0))
    if input_gain < 0.0:
        raise ConfigError(f"{source}: 'input_gain' must be >= 0.0, got {input_gain}")

    on_startup: list[ActionEntry] = []
    raw_startup = raw.get("on_startup")
    if raw_startup is not None:
        if not isinstance(raw_startup, list):
            raise ConfigError(f"{source}: 'on_startup' must be a list")
        on_startup = _parse_actions(raw_startup, "on_startup")

    # top-level triggers are the global fallback; absent means no fallback
    raw_triggers = raw.get("triggers")
    if raw_triggers is None:
        triggers: list[Trigger] = []
    elif not isinstance(raw_triggers, list):
        raise ConfigError(f"{source}: 'triggers' must be a list if present")
    else:
        triggers = _parse_triggers(raw_triggers, "triggers")

    audio_card_name = str(raw.get("audio_card_name", "NewPie"))

    audio_sample_rates_raw = raw.get("audio_sample_rates") or {}
    if not isinstance(audio_sample_rates_raw, dict):
        raise ConfigError(
            f"{source}: 'audio_sample_rates' must be a mapping if present"
        )
    audio_sample_rates = {
        "usb": int(audio_sample_rates_raw.get("usb", 48000)),
        "bluetooth": int(audio_sample_rates_raw.get("bluetooth", 16000)),
        "internal": int(audio_sample_rates_raw.get("internal", 48000)),
    }

    audio_post_playback_ms = int(raw.get("audio_post_playback_ms", 100))
    audio_tone_preroll_ms = int(raw.get("audio_tone_preroll_ms", 300))
    audio_mic_gain = int(raw.get("audio_mic_gain", 300))
    reconnect_delay = int(raw.get("reconnect_delay", 5))
    mqtt_queue_max = int(raw.get("mqtt_queue_max", 200))
    stt_vad_silence_ms = int(raw.get("stt_vad_silence_ms", 700))
    stt_stage1_vad_silence_ms = int(raw.get("stt_stage1_vad_silence_ms", 500))
    stt_stage1_rms_threshold = float(raw.get("stt_stage1_rms_threshold", 0.02))
    config_poll_interval = int(raw.get("config_poll_interval", 2))

    # actions_file: external trigger definitions writable by the learning agent
    actions_file_raw = raw.get("actions_file")
    actions_file: str | None = str(actions_file_raw) if actions_file_raw else None

    # llm: optional Ollama-backed conversation engine
    llm: LLMConfig | None = None
    raw_llm = raw.get("llm")
    if raw_llm is not None:
        if not isinstance(raw_llm, dict):
            raise ConfigError(f"{source}: 'llm' must be a mapping if present")
        llm = _parse_llm_config(raw_llm, source)

    return ActionsConfig(
        wake_words=wake_words,
        command_timeout=command_timeout,
        triggers=triggers,
        on_startup=on_startup,
        recognition_mode=recognition_mode,
        wake_confidence=wake_confidence,
        wake_tone=wake_tone,
        tts_preroll_ms=tts_preroll_ms,
        tts_backend=tts_backend,
        tts_voice=tts_voice,
        stt_backend=stt_backend,
        stt_model_path=stt_model_path,
        output_volume=output_volume,
        input_gain=input_gain,
        audio_card_name=audio_card_name,
        audio_sample_rates=audio_sample_rates,
        audio_post_playback_ms=audio_post_playback_ms,
        audio_tone_preroll_ms=audio_tone_preroll_ms,
        audio_mic_gain=audio_mic_gain,
        reconnect_delay=reconnect_delay,
        mqtt_queue_max=mqtt_queue_max,
        stt_vad_silence_ms=stt_vad_silence_ms,
        stt_stage1_vad_silence_ms=stt_stage1_vad_silence_ms,
        stt_stage1_rms_threshold=stt_stage1_rms_threshold,
        config_poll_interval=config_poll_interval,
        actions_file=actions_file,
        llm=llm,
    )


def load_web_config(base_dir: str | Path = ".") -> dict:
    """Return the optional web: section from config.yaml as a dict (keys: port, enabled)."""
    p = Path(base_dir) / "config.yaml"
    if not p.exists():
        return {}
    try:
        with p.open() as f:
            raw = yaml.safe_load(f) or {}
        return raw.get("web", {}) if isinstance(raw, dict) else {}
    except Exception:
        return {}
