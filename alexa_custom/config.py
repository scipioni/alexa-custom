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


# ---------------------------------------------------------------------------
# Leaf dataclasses (shared with action parsing)
# ---------------------------------------------------------------------------


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

    @property
    def patterns(self) -> list[str]:
        return [self.phrase] + self.aliases


@dataclass
class WakeWordGroup:
    word: str
    aliases: list[str] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    lang: str = "it-IT"
    id: str = ""  # stable key for wake_triggers in action files; defaults to word
    skip_unmatched_inline: bool = (
        False  # if True, silently skip when inline_cmd doesn't match any trigger
    )

    def __post_init__(self):
        if not self.id:
            self.id = self.word


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


# ---------------------------------------------------------------------------
# Sub-config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AudioWebRTCConfig:
    agc: bool = True
    aec: bool = True
    noise_suppression: bool = True
    high_pass_filter: bool = True


@dataclass
class AudioConfig:
    card_name: str = "NewPie"
    input_device: str | None = None
    output_device: str | None = None
    output_volume: float = 0.5
    input_gain: float = 1.0
    sample_rates: dict = field(
        default_factory=lambda: {"usb": 48000, "bluetooth": 16000, "internal": 48000}
    )
    post_playback_ms: int = 100
    tone_preroll_ms: int = 300
    webrtc: AudioWebRTCConfig = field(default_factory=AudioWebRTCConfig)


@dataclass
class STTStage1Config:
    backend: str = "vosk"
    model_path: str | None = None
    confidence: float = 0.65
    # "first" preserves original behaviour (words[0] only).
    # "min" requires every decoded token to clear the bar (strictest).
    # "mean" uses the average across tokens (moderate).
    confidence_mode: str = "first"
    vad_silence_ms: int = 500
    rms_threshold: float = 0.02
    min_speech_ms: int = 200
    vosk_grammar: bool = False
    keyword_spotter: bool = False
    keywords_score: float = 1.0
    keywords_threshold: float = 0.25
    model_variant: str = "auto"


@dataclass
class STTStage2Config:
    backend: str = "vosk"
    model_path: str | None = None
    model_variant: str = "auto"


@dataclass
class STTConfig:
    vad_silence_ms: int = 500
    flush_ms: int = 300
    stage1: STTStage1Config = field(default_factory=STTStage1Config)
    stage2: STTStage2Config = field(default_factory=STTStage2Config)


@dataclass
class TTSConfig:
    backend: str = "piper"
    voice: str = "it_IT-paola-medium"
    preroll_ms: int = 300


_VALID_MODES = {"two-stage", "single-stage"}
_VALID_ALGORITHMS = {"token_set_ratio", "levenshtein", "ratio"}


@dataclass
class RecognitionConfig:
    mode: str = "two-stage"
    command_timeout: float = 2.5
    # Absolute cap on stage-2 capture once speech has started; the window
    # slides while the user keeps speaking, bounded by this. 0 disables sliding.
    command_max_timeout: float = 8.0
    wake_tone: str = "wake"
    partial_matching: bool = True
    partial_stability_ms: int = 150
    partial_stability_reads: int = 3
    matching_algorithm: str = "token_set_ratio"
    matching_threshold: float = 70.0
    reply_matching_algorithm: str = "levenshtein"
    reply_matching_threshold: float = 80.0
    phonetic_matching: bool = True
    phonetic_threshold: float = 0.7


@dataclass
class MQTTConfig:
    host: str = ""
    port: int = 1883
    topic_prefix: str = "alexa"
    node_id: str | None = None
    queue_max: int = 200


@dataclass
class WebConfig:
    port: int = 8080
    cpu_limit: int = 4


@dataclass
class SystemConfig:
    reconnect_delay: int = 5
    config_poll_interval: int = 2
    empty_room_timeout: int = 0
    wait_for_participant: bool = True
    answer_timeout: float = 60


@dataclass
class ActionsDirectoryConfig:
    dir: str = "conf/actions"
    learn_file: str = "conf/actions/learned.yaml"


@dataclass
class LLMConfig:
    backend: str
    host: str
    model: str = "ssfdre38/gemma4-nano"
    context_turns: int = 10
    context_window_secs: int = 60
    fallback_on_no_match: bool = False
    learn_commands: bool = True
    system_prompt: str | None = None
    request_timeout: float = 60.0
    exit_phrases: list[str] = field(default_factory=lambda: list(_DEFAULT_EXIT_PHRASES))
    api_key: str = ""


# ---------------------------------------------------------------------------
# Secrets dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LiveKitSecretsConfig:
    url: str = ""
    api_key: str = ""
    api_secret: str = ""
    room: str = ""


@dataclass
class TelegramSecretsConfig:
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class MQTTSecretsConfig:
    username: str = ""
    password: str = ""


@dataclass
class DisplayConfig:
    enabled: bool = False
    backend: str = "auto"
    transport: str = "auto"
    i2c_bus: int = 0
    i2c_address: int = 0x3C
    i2c_width: int = 128
    i2c_height: int = 64


@dataclass
class SecretsConfig:
    livekit: LiveKitSecretsConfig = field(default_factory=LiveKitSecretsConfig)
    telegram: TelegramSecretsConfig = field(default_factory=TelegramSecretsConfig)
    llm_host: str | None = None
    mqtt: MQTTSecretsConfig = field(default_factory=MQTTSecretsConfig)


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


@dataclass
class ActionsData:
    triggers: list[Trigger] = field(default_factory=list)
    wake_triggers: dict[str, list[Trigger]] = field(default_factory=dict)


@dataclass
class ActionsConfig:
    wake_words: list[WakeWordGroup]
    triggers: list[Trigger]  # merged global fallback; may be empty
    on_startup: list[ActionEntry] = field(default_factory=list)
    audio: AudioConfig = field(default_factory=AudioConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    recognition: RecognitionConfig = field(default_factory=RecognitionConfig)
    mqtt: MQTTConfig | None = None
    web: WebConfig = field(default_factory=WebConfig)
    system: SystemConfig = field(default_factory=SystemConfig)
    actions: ActionsDirectoryConfig = field(default_factory=ActionsDirectoryConfig)
    llm: LLMConfig | None = None
    display: DisplayConfig | None = None


# ---------------------------------------------------------------------------
# Primitive parsers (actions, triggers, wake word groups)
# ---------------------------------------------------------------------------


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
    seen: dict[str, int] = {}

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
        raw_id = entry.get("id")
        group_id = str(raw_id).strip() if raw_id else word
        skip_unmatched_inline = bool(entry.get("skip_unmatched_inline", False))

        groups.append(
            WakeWordGroup(
                word=word,
                aliases=aliases,
                triggers=group_triggers,
                lang=lang,
                id=group_id,
                skip_unmatched_inline=skip_unmatched_inline,
            )
        )

    return groups


# ---------------------------------------------------------------------------
# Sub-config parsers
# ---------------------------------------------------------------------------


def _parse_audio_config(raw: dict) -> AudioConfig:
    webrtc_raw = raw.get("webrtc") or {}
    if not isinstance(webrtc_raw, dict):
        webrtc_raw = {}
    webrtc = AudioWebRTCConfig(
        agc=bool(webrtc_raw.get("agc", True)),
        aec=bool(webrtc_raw.get("aec", True)),
        noise_suppression=bool(webrtc_raw.get("noise_suppression", True)),
        high_pass_filter=bool(webrtc_raw.get("high_pass_filter", True)),
    )

    sample_rates_raw = raw.get("sample_rates") or {}
    if not isinstance(sample_rates_raw, dict):
        sample_rates_raw = {}
    sample_rates = {
        "usb": int(sample_rates_raw.get("usb", 48000)),
        "bluetooth": int(sample_rates_raw.get("bluetooth", 16000)),
        "internal": int(sample_rates_raw.get("internal", 48000)),
    }

    output_volume = float(raw.get("output_volume", 0.5))
    if not (0.0 <= output_volume <= 1.0):
        raise ConfigError(
            f"'audio.output_volume' must be between 0.0 and 1.0, got {output_volume}"
        )

    input_gain = float(raw.get("input_gain", 1.0))
    if input_gain < 0.0:
        raise ConfigError(f"'audio.input_gain' must be >= 0.0, got {input_gain}")

    input_device = raw.get("input_device") or None
    output_device = raw.get("output_device") or None

    return AudioConfig(
        card_name=str(raw.get("card_name", "NewPie")),
        input_device=str(input_device) if input_device else None,
        output_device=str(output_device) if output_device else None,
        output_volume=output_volume,
        input_gain=input_gain,
        sample_rates=sample_rates,
        post_playback_ms=int(raw.get("post_playback_ms", 100)),
        tone_preroll_ms=int(raw.get("tone_preroll_ms", 300)),
        webrtc=webrtc,
    )


def _parse_stt_stage1_config(raw: dict) -> STTStage1Config:
    backend = str(raw.get("backend", "vosk"))
    if backend not in ("vosk", "sherpa-onnx"):
        raise ConfigError(
            f"'stt.stage1.backend' must be 'vosk' or 'sherpa-onnx', got {backend!r}"
        )
    model_path_raw = raw.get("model_path")
    confidence_mode = str(raw.get("confidence_mode", "first"))
    if confidence_mode not in ("first", "min", "mean"):
        raise ConfigError(
            f"'stt.stage1.confidence_mode' must be 'first', 'min', or 'mean', got {confidence_mode!r}"
        )
    model_variant = str(raw.get("model_variant", "auto"))
    _VALID_VARIANTS = {"auto", "transducer", "zipformer2-ctc", "paraformer", "nemo_ctc"}
    if model_variant not in _VALID_VARIANTS:
        raise ConfigError(
            f"'stt.stage1.model_variant' must be one of {sorted(_VALID_VARIANTS)}, got {model_variant!r}"
        )
    return STTStage1Config(
        backend=backend,
        model_path=str(model_path_raw) if model_path_raw else None,
        confidence=float(raw.get("confidence", 0.65)),
        confidence_mode=confidence_mode,
        vad_silence_ms=int(raw.get("vad_silence_ms", 500)),
        rms_threshold=float(raw.get("rms_threshold", 0.02)),
        min_speech_ms=int(raw.get("min_speech_ms", 300)),
        vosk_grammar=bool(raw.get("vosk_grammar", False)),
        keyword_spotter=bool(raw.get("keyword_spotter", False)),
        keywords_score=float(raw.get("keywords_score", 1.0)),
        keywords_threshold=float(raw.get("keywords_threshold", 0.25)),
        model_variant=model_variant,
    )


def _parse_stt_stage2_config(raw: dict) -> STTStage2Config:
    backend = str(raw.get("backend", "vosk"))
    if backend not in ("vosk", "sherpa-onnx", "nemo-offline", "whisper-cpp"):
        raise ConfigError(
            f"'stt.stage2.backend' must be 'vosk', 'sherpa-onnx', 'nemo-offline', or 'whisper-cpp', got {backend!r}"
        )
    model_path_raw = raw.get("model_path")
    model_variant = str(raw.get("model_variant", "auto"))
    _VALID_VARIANTS = {"auto", "transducer", "zipformer2-ctc", "paraformer", "nemo_ctc"}
    if model_variant not in _VALID_VARIANTS:
        raise ConfigError(
            f"'stt.stage2.model_variant' must be one of {sorted(_VALID_VARIANTS)}, got {model_variant!r}"
        )
    return STTStage2Config(
        backend=backend,
        model_path=str(model_path_raw) if model_path_raw else None,
        model_variant=model_variant,
    )


def _parse_stt_config(raw: dict) -> STTConfig:
    stage1_raw = raw.get("stage1") or {}
    if not isinstance(stage1_raw, dict):
        raise ConfigError("'stt.stage1' must be a mapping if present")
    stage2_raw = raw.get("stage2") or {}
    if not isinstance(stage2_raw, dict):
        raise ConfigError("'stt.stage2' must be a mapping if present")
    return STTConfig(
        vad_silence_ms=int(raw.get("vad_silence_ms", 700)),
        flush_ms=int(raw.get("flush_ms", 300)),
        stage1=_parse_stt_stage1_config(stage1_raw),
        stage2=_parse_stt_stage2_config(stage2_raw),
    )


def _parse_tts_config(raw: dict) -> TTSConfig:
    backend = str(raw.get("backend", "piper"))
    return TTSConfig(
        backend=backend,
        voice=str(raw.get("voice", "it_IT-paola-medium")),
        preroll_ms=int(raw.get("preroll_ms", 400)),
    )


def _parse_recognition_config(raw: dict) -> RecognitionConfig:
    mode = str(raw.get("mode", "two-stage"))
    if mode not in _VALID_MODES:
        raise ConfigError(
            f"'recognition.mode' must be one of {sorted(_VALID_MODES)}, got {mode!r}"
        )
    algo = str(raw.get("matching_algorithm", "token_set_ratio"))
    if algo not in _VALID_ALGORITHMS:
        raise ConfigError(
            f"'recognition.matching_algorithm' must be one of {sorted(_VALID_ALGORITHMS)}, got {algo!r}"
        )
    reply_algo = str(raw.get("reply_matching_algorithm", "levenshtein"))
    if reply_algo not in _VALID_ALGORITHMS:
        raise ConfigError(
            f"'recognition.reply_matching_algorithm' must be one of {sorted(_VALID_ALGORITHMS)}, got {reply_algo!r}"
        )
    return RecognitionConfig(
        mode=mode,
        command_timeout=float(raw.get("command_timeout", 3.0)),
        command_max_timeout=float(raw.get("command_max_timeout", 8.0)),
        wake_tone=str(raw.get("wake_tone", "wake")),
        partial_matching=bool(raw.get("partial_matching", True)),
        partial_stability_ms=int(raw.get("partial_stability_ms", 150)),
        partial_stability_reads=int(raw.get("partial_stability_reads", 3)),
        matching_algorithm=algo,
        matching_threshold=float(raw.get("matching_threshold", 70.0)),
        reply_matching_algorithm=reply_algo,
        reply_matching_threshold=float(raw.get("reply_matching_threshold", 80.0)),
        phonetic_matching=bool(raw.get("phonetic_matching", True)),
        phonetic_threshold=float(raw.get("phonetic_threshold", 0.7)),
    )


def _parse_mqtt_config(raw: dict) -> MQTTConfig | None:
    host = raw.get("host")
    if not host:
        return None
    return MQTTConfig(
        host=str(host),
        port=int(raw.get("port", 1883)),
        topic_prefix=str(raw.get("topic_prefix", "alexa")),
        node_id=str(raw.get("node_id")) if raw.get("node_id") else None,
        queue_max=int(raw.get("queue_max", 200)),
    )


def _parse_system_config(raw: dict) -> SystemConfig:
    return SystemConfig(
        reconnect_delay=int(raw.get("reconnect_delay", 5)),
        config_poll_interval=int(raw.get("config_poll_interval", 2)),
        empty_room_timeout=int(raw.get("empty_room_timeout", 0)),
        wait_for_participant=bool(raw.get("wait_for_participant", True)),
        answer_timeout=float(raw.get("answer_timeout", 60)),
    )


def _parse_actions_dir_config(raw: dict) -> ActionsDirectoryConfig:
    return ActionsDirectoryConfig(
        dir=str(raw.get("dir", "conf/actions")),
        learn_file=str(raw.get("learn_file", "conf/actions/learned.yaml")),
    )


def _parse_llm_config(
    raw_llm: dict, source: str, host_override: str | None = None
) -> LLMConfig:
    backend = str(raw_llm.get("backend", ""))
    if backend not in {"ollama", "openai"}:
        raise ConfigError(
            f"{source}: 'llm.backend' must be 'ollama' or 'openai', got {backend!r}"
        )
    host = host_override or raw_llm.get("host")
    if not host or not isinstance(host, str):
        raise ConfigError(
            f"{source}: 'llm.host' is required (set in conf/secrets.yaml)"
        )
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
        fallback_on_no_match=bool(raw_llm.get("fallback_on_no_match", False)),
        learn_commands=bool(raw_llm.get("learn_commands", True)),
        system_prompt=raw_llm.get("system_prompt") or None,
        request_timeout=float(raw_llm.get("request_timeout", 60.0)),
        exit_phrases=exit_phrases,
        api_key=str(raw_llm.get("api_key", "")),
    )


# ---------------------------------------------------------------------------
# Multi-file action loading
# ---------------------------------------------------------------------------


def _parse_actions_file_raw(path: Path, source: str) -> dict:
    """Load a single action YAML file; return raw dict."""
    try:
        with path.open() as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{source}: YAML parse error: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: must be a YAML mapping at the top level")
    return raw


def _load_actions_dir(
    dir_path: Path,
    wake_words: list[WakeWordGroup],
    system_file: str = "system.yaml",
) -> tuple[list[ActionEntry], ActionsData]:
    """Load all .yaml files from dir_path; system_file first, rest alphabetically.

    Returns (on_startup_actions, merged_actions_data).
    on_startup is only read from system_file.
    """
    if not dir_path.is_dir():
        logger.warning("Actions directory not found: %s", dir_path)
        return [], ActionsData()

    # Collect files: system first, then others alphabetically
    system_path = dir_path / system_file
    other_paths = sorted(p for p in dir_path.glob("*.yaml") if p.name != system_file)
    paths: list[tuple[Path, bool]] = []  # (path, is_system)
    if system_path.exists():
        paths.append((system_path, True))
    for p in other_paths:
        paths.append((p, False))

    id_set = {g.id for g in wake_words}

    on_startup: list[ActionEntry] = []
    all_triggers: list[Trigger] = []
    all_wake_triggers: dict[str, list[Trigger]] = {}

    for path, is_system in paths:
        source = str(path)
        try:
            raw = _parse_actions_file_raw(path, source)
        except ConfigError as e:
            logger.error("Skipping action file %s: %s", path, e)
            continue

        # on_startup: only from system file
        if is_system:
            raw_startup = raw.get("on_startup")
            if raw_startup is not None:
                if not isinstance(raw_startup, list):
                    logger.warning("%s: 'on_startup' must be a list — ignored", source)
                else:
                    on_startup = _parse_actions(raw_startup, f"{source}:on_startup")
        elif raw.get("on_startup") is not None:
            logger.debug(
                "%s: 'on_startup' ignored (only honoured in %s)", source, system_file
            )

        # triggers: concatenate in load order
        raw_triggers = raw.get("triggers")
        if raw_triggers is not None:
            if not isinstance(raw_triggers, list):
                logger.warning("%s: 'triggers' must be a list — ignored", source)
            else:
                all_triggers.extend(_parse_triggers(raw_triggers, f"{source}:triggers"))

        # wake_triggers: merge per word, concatenate in load order
        raw_wake = raw.get("wake_triggers")
        if raw_wake is not None:
            if not isinstance(raw_wake, dict):
                logger.warning(
                    "%s: 'wake_triggers' must be a mapping — ignored", source
                )
            else:
                for word, raw_wt in raw_wake.items():
                    if word not in id_set:
                        logger.debug(
                            "%s: wake_triggers key %r has no matching wake word group — ignored",
                            source,
                            word,
                        )
                        continue
                    if not isinstance(raw_wt, list):
                        logger.warning(
                            "%s: 'wake_triggers.%s' must be a list — ignored",
                            source,
                            word,
                        )
                        continue
                    wt = _parse_triggers(raw_wt, f"{source}:wake_triggers.{word}")
                    if word in all_wake_triggers:
                        all_wake_triggers[word].extend(wt)
                    else:
                        all_wake_triggers[word] = wt

    return on_startup, ActionsData(
        triggers=all_triggers, wake_triggers=all_wake_triggers
    )


# ---------------------------------------------------------------------------
# Secrets loader
# ---------------------------------------------------------------------------


def load_secrets(path: str | Path = "conf/secrets.yaml") -> SecretsConfig:
    """Load conf/secrets.yaml, apply values to os.environ, return SecretsConfig.

    Missing file is silently ignored (all fields default to empty strings).
    """
    p = Path(path)
    if not p.exists():
        logger.debug("Secrets file not found: %s — skipping", p)
        return SecretsConfig()

    try:
        with p.open() as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"conf/secrets.yaml parse error: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError("conf/secrets.yaml must be a YAML mapping at the top level")

    lk_raw = raw.get("livekit") or {}
    lk = LiveKitSecretsConfig(
        url=str(lk_raw.get("url", "")),
        api_key=str(lk_raw.get("api_key", "")),
        api_secret=str(lk_raw.get("api_secret", "")),
        room=str(lk_raw.get("room", "")),
    )
    tg_raw = raw.get("telegram") or {}
    tg = TelegramSecretsConfig(
        bot_token=str(tg_raw.get("bot_token", "")),
        chat_id=str(tg_raw.get("chat_id", "")),
    )
    mqtt_raw = raw.get("mqtt") or {}
    mq = MQTTSecretsConfig(
        username=str(mqtt_raw.get("username", "")),
        password=str(mqtt_raw.get("password", "")),
    )
    llm_host = raw.get("llm_host") or None
    if llm_host:
        llm_host = str(llm_host)

    secrets = SecretsConfig(livekit=lk, telegram=tg, llm_host=llm_host, mqtt=mq)

    # Apply to os.environ
    env_updates: list[str] = []
    if lk.url:
        os.environ["LIVEKIT_URL"] = lk.url
        env_updates.append("LIVEKIT_URL")
    if lk.api_key:
        os.environ["LIVEKIT_API_KEY"] = lk.api_key
        env_updates.append("LIVEKIT_API_KEY")
    if lk.api_secret:
        os.environ["LIVEKIT_API_SECRET"] = lk.api_secret
        env_updates.append("LIVEKIT_API_SECRET")
    if lk.room:
        os.environ["LIVEKIT_ROOM"] = lk.room
        env_updates.append("LIVEKIT_ROOM")
    if tg.bot_token:
        os.environ["TELEGRAM_BOT_TOKEN"] = tg.bot_token
        env_updates.append("TELEGRAM_BOT_TOKEN")
    if tg.chat_id:
        os.environ["TELEGRAM_CHAT_ID"] = tg.chat_id
        env_updates.append("TELEGRAM_CHAT_ID")
    if mq.username:
        os.environ["MQTT_USERNAME"] = mq.username
        env_updates.append("MQTT_USERNAME")
    if mq.password:
        os.environ["MQTT_PASSWORD"] = mq.password
        env_updates.append("MQTT_PASSWORD")

    if env_updates:
        logger.debug("Applied secrets env keys: %s", ", ".join(env_updates))

    return secrets


# ---------------------------------------------------------------------------
# Main config loader
# ---------------------------------------------------------------------------


def load_config(
    path: str | Path = "conf/config.yaml",
    secrets: "SecretsConfig | None" = None,
) -> "ActionsConfig | None":
    """Load conf/config.yaml and merge action files from conf/actions/."""
    p = Path(path)
    if not p.exists():
        return None

    try:
        with p.open() as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"conf/config.yaml parse error: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError("conf/config.yaml must be a YAML mapping at the top level")

    if "env" in raw:
        raise ConfigError(
            "conf/config.yaml: 'env:' key is not supported — "
            "move credentials to conf/secrets.yaml"
        )

    cfg = _parse_actions_config(raw, source=str(p), secrets=secrets)

    return cfg


def _merge_user_wake_words(wake_words: list[WakeWordGroup], user_path: Path) -> None:
    """Append wake word groups from user.yaml that are not already in wake_words."""
    try:
        with user_path.open() as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.warning("user.yaml parse error, skipping: %s", e)
        return

    if not isinstance(raw, dict):
        logger.warning("user.yaml must be a YAML mapping at the top level, skipping")
        return

    raw_wake_words = raw.get("wake_words")
    if not raw_wake_words:
        return
    if not isinstance(raw_wake_words, list):
        logger.warning("user.yaml: 'wake_words' must be a list, skipping")
        return

    try:
        user_groups = _parse_wake_word_groups(raw_wake_words, str(user_path))
    except ConfigError as e:
        logger.warning("user.yaml wake_words error, skipping: %s", e)
        return

    existing_ids = {g.id for g in wake_words}
    added = 0
    for group in user_groups:
        if group.id in existing_ids:
            logger.debug(
                "user.yaml: wake word %r (id=%r) already defined in config.yaml, skipping",
                group.word,
                group.id,
            )
        else:
            wake_words.append(group)
            existing_ids.add(group.id)
            added += 1

    if added:
        logger.info("user.yaml: merged %d wake word group(s)", added)


def _parse_actions_config(
    raw: dict,
    source: str = "config",
    secrets: SecretsConfig | None = None,
) -> ActionsConfig:
    """Parse a raw YAML dict into ActionsConfig."""
    raw_wake_words = raw.get("wake_words")
    if (
        not raw_wake_words
        or not isinstance(raw_wake_words, list)
        or len(raw_wake_words) == 0
    ):
        raise ConfigError(f"{source}: 'wake_words' must be a non-empty list")

    wake_words = _parse_wake_word_groups(raw_wake_words, source)

    # Merge wake words from user.yaml (optional, sits next to config.yaml)
    config_dir = Path(source).parent if source != "config" else Path(".")
    user_path = config_dir / "user.yaml"
    if user_path.exists():
        _merge_user_wake_words(wake_words, user_path)

    audio_raw = raw.get("audio") or {}
    if not isinstance(audio_raw, dict):
        raise ConfigError(f"{source}: 'audio' must be a mapping if present")
    audio = _parse_audio_config(audio_raw)

    stt_raw = raw.get("stt") or {}
    if not isinstance(stt_raw, dict):
        raise ConfigError(f"{source}: 'stt' must be a mapping if present")
    stt = _parse_stt_config(stt_raw)

    tts_raw = raw.get("tts") or {}
    if not isinstance(tts_raw, dict):
        raise ConfigError(f"{source}: 'tts' must be a mapping if present")
    tts = _parse_tts_config(tts_raw)

    recognition_raw = raw.get("recognition") or {}
    if not isinstance(recognition_raw, dict):
        raise ConfigError(f"{source}: 'recognition' must be a mapping if present")
    recognition = _parse_recognition_config(recognition_raw)

    mqtt_raw = raw.get("mqtt") or {}
    if not isinstance(mqtt_raw, dict):
        raise ConfigError(f"{source}: 'mqtt' must be a mapping if present")
    mqtt = _parse_mqtt_config(mqtt_raw)

    web_raw = raw.get("web") or {}
    if not isinstance(web_raw, dict):
        raise ConfigError(f"{source}: 'web' must be a mapping if present")
    web = WebConfig(
        port=int(web_raw.get("port", 8080)),
        cpu_limit=int(web_raw.get("cpu_limit", 4)),
    )

    system_raw = raw.get("system") or {}
    if not isinstance(system_raw, dict):
        raise ConfigError(f"{source}: 'system' must be a mapping if present")
    system = _parse_system_config(system_raw)

    actions_raw = raw.get("actions") or {}
    if not isinstance(actions_raw, dict):
        raise ConfigError(f"{source}: 'actions' must be a mapping if present")
    actions_dir_cfg = _parse_actions_dir_config(actions_raw)

    # Display config
    display: DisplayConfig | None = None
    raw_display = raw.get("display")
    if raw_display is not None:
        if not isinstance(raw_display, dict):
            raise ConfigError(f"{source}: 'display' must be a mapping if present")
        display = DisplayConfig(
            enabled=bool(raw_display.get("enabled", False)),
            backend=str(raw_display.get("backend", "auto")),
            transport=str(raw_display.get("transport", "auto")),
            i2c_bus=int(raw_display.get("i2c_bus", 0)),
            i2c_address=int(raw_display.get("i2c_address", "0x3C"), 0),
            i2c_width=int(raw_display.get("i2c_width", 128)),
            i2c_height=int(raw_display.get("i2c_height", 64)),
        )

    # LLM: merge llm_host from secrets if available
    llm: LLMConfig | None = None
    raw_llm = raw.get("llm")
    if raw_llm is not None:
        if not isinstance(raw_llm, dict):
            raise ConfigError(f"{source}: 'llm' must be a mapping if present")
        llm_host_override = (secrets.llm_host if secrets else None) or raw_llm.get(
            "host"
        )
        if not llm_host_override:
            logger.warning(
                "%s: LLM disabled — 'llm_host' not set in conf/secrets.yaml or 'llm.host' in config",
                source,
            )
        else:
            try:
                llm = _parse_llm_config(
                    raw_llm, source, host_override=str(llm_host_override)
                )
            except ConfigError as e:
                logger.warning("LLM config error — LLM disabled: %s", e)

    # Set audio WebRTC env vars from config
    webrtc = audio.webrtc
    os.environ.setdefault("MIC_AGC", "1" if webrtc.agc else "0")
    os.environ.setdefault("MIC_AEC", "1" if webrtc.aec else "0")
    os.environ.setdefault(
        "MIC_NOISE_SUPPRESSION", "1" if webrtc.noise_suppression else "0"
    )
    os.environ.setdefault(
        "MIC_HIGH_PASS_FILTER", "1" if webrtc.high_pass_filter else "0"
    )

    # Load and merge action files
    config_dir = Path(source).parent if source != "config" else Path(".")
    actions_dir = Path(actions_dir_cfg.dir)
    if not actions_dir.is_absolute():
        actions_dir = config_dir.parent / actions_dir_cfg.dir

    on_startup, actions_data = _load_actions_dir(actions_dir, wake_words)

    # Merge wake_triggers into wake word groups (keyed by group id)
    id_map = {g.id: g for g in wake_words}
    for group_id, wt_list in actions_data.wake_triggers.items():
        if group_id in id_map:
            id_map[group_id].triggers = id_map[group_id].triggers + wt_list

    return ActionsConfig(
        wake_words=wake_words,
        triggers=actions_data.triggers,
        on_startup=on_startup,
        audio=audio,
        stt=stt,
        tts=tts,
        recognition=recognition,
        mqtt=mqtt,
        web=web,
        system=system,
        actions=actions_dir_cfg,
        llm=llm,
        display=display,
    )
