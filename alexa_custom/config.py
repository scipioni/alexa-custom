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
    commands: list[str] = field(default_factory=list)  # primary field
    actions: list[ActionEntry] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    with_wake: bool = True  # False = fires without a wake word
    follow_up: bool | None = None
    min_word_overlap: float | None = None
    tag: str = ""
    # Legacy compat: populated from commands[0] / commands[1:] by the parser.
    # match_trigger_with_score() uses these — do not set directly.
    phrase: str = ""
    aliases: list[str] = field(default_factory=list)
    # Deprecated: trigger-level wake_words (old routing); kept to hold the raw
    # YAML value for migration warnings. Not used for dispatch routing.
    wake_words: list[str] | None = None


@dataclass
class WakeWordGroup:
    """Deprecated: wake_words is now a flat list[str]. Kept for backward compat."""

    word: str
    aliases: list[str] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    lang: str = "it-IT"
    id: str = ""
    skip_unmatched_inline: bool = False

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
class GStreamerCaptureConfig:
    source: str = "pulsesrc"           # pulsesrc | pipewiresrc
    noise_suppression: bool = True
    noise_suppression_level: int = 2   # 0=mild 1=moderate 2=high 3=very-high
    agc: bool = True
    agc_target_level_dbfs: int = -3    # dBFS target (negative; abs() passed to GStreamer, range 0–31)
    agc_compression_gain_db: int = 9   # max makeup gain dB
    high_pass_filter: bool = True
    compressor: bool = False           # audiodynamic compressor stage
    compressor_threshold: float = 0.1  # normalized 0.0–1.0
    compressor_ratio: float = 3.0
    profiles: dict = field(default_factory=dict)  # name → {field: override_value}


def resolve_gst_profile(base: "GStreamerCaptureConfig", profile_name: str) -> "GStreamerCaptureConfig":
    """Return a GStreamerCaptureConfig with named profile overrides applied over base.

    Unknown profile names silently fall back to base (no crash at runtime).
    Non-GStreamer keys (rms_threshold, vad_silence_ms) are silently skipped here
    and extracted separately by get_gst_profile_stt_overrides().
    """
    import dataclasses as _dc

    overrides = base.profiles.get(profile_name) or {}
    if not overrides:
        return base
    _valid = {f.name for f in _dc.fields(base) if f.name != "profiles"}
    merged = {f.name: getattr(base, f.name) for f in _dc.fields(base) if f.name != "profiles"}
    for k, v in overrides.items():
        if k in _valid:
            merged[k] = v
    return GStreamerCaptureConfig(**merged, profiles=base.profiles)


_STT_PROFILE_KEYS = {"rms_threshold", "vad_silence_ms"}


def get_gst_profile_stt_overrides(base: "GStreamerCaptureConfig", profile_name: str) -> dict:
    """Return STT-level keys (rms_threshold, vad_silence_ms) from a profile dict.

    These keys are not GStreamer params so resolve_gst_profile ignores them.
    The recognition loop applies them after a profile-triggered capture restart.
    """
    raw = base.profiles.get(profile_name) or {}
    return {k: v for k, v in raw.items() if k in _STT_PROFILE_KEYS}


@dataclass
class AudioConfig:
    card_name: str | None = None
    input_device: str | None = None
    output_device: str | None = None
    output_volume: float = 0.5
    input_gain: float = 1.0
    sample_rates: dict = field(
        default_factory=lambda: {"usb": 48000, "bluetooth": 16000, "internal": 48000}
    )
    post_playback_ms: int = 100
    tone_preroll_ms: int = 50
    webrtc: AudioWebRTCConfig = field(default_factory=AudioWebRTCConfig)
    gstreamer: GStreamerCaptureConfig = field(default_factory=GStreamerCaptureConfig)


# ---------------------------------------------------------------------------
# Deprecated STT stage configs — kept as stubs for backward compat
# (wake_eval.py, bench_stt.py, and old tests still reference these)
# ---------------------------------------------------------------------------


@dataclass
class STTStage1Config:
    """Deprecated: use the flat STTConfig fields instead."""

    backend: str = "vosk"
    model_path: str | None = None
    confidence: float = 0.65
    confidence_mode: str = "first"
    vad_silence_ms: int = 500
    rms_threshold: float = 0.02
    adaptive_rms: bool = True
    adaptive_rms_margin: float = 0.01
    min_speech_ms: int = 200
    vosk_grammar: bool = True
    keyword_spotter: bool = False
    keywords_score: float = 1.0
    keywords_threshold: float = 0.35
    hotwords_score: float = 1.5
    max_partial_words: int = 8
    wake_match_threshold: float = 0.5
    num_threads: int = 2


@dataclass
class STTStage2Config:
    """Deprecated: use the flat STTConfig fields instead."""

    backend: str = "vosk"
    model_path: str | None = None
    vosk_grammar: bool = False
    num_threads: int = 2


# ---------------------------------------------------------------------------
# New flat STTConfig (replaces STTStage1Config + STTStage2Config container)
# ---------------------------------------------------------------------------


@dataclass
class STTConfig:
    backend: str = "vosk"
    model_path: str | None = None
    num_threads: int = 2
    # 900 ms confirmed clean on-board (vosk, no utterance fragmentation)
    vad_silence_ms: int = 900
    rms_threshold: float = 0.02
    adaptive_rms: bool = True
    adaptive_rms_margin: float = 0.01
    min_speech_ms: int = 200
    wake_match_threshold: float = 0.5
    mono_capture: bool = False
    capture_backend: str = "parec"     # parec | gstreamer


@dataclass
class TTSConfig:
    backend: str = "piper"
    voice: str = "it_IT-paola-medium"
    preroll_ms: int = 100


_VALID_ALGORITHMS = {"token_set_ratio", "token_sort_ratio", "levenshtein", "ratio"}


@dataclass
class RecognitionConfig:
    # Time (seconds) the recently-woken state stays open after a wake word.
    wake_window: float = 8.0
    wake_tone: str = "wake"
    matching_algorithm: str = "token_sort_ratio"
    matching_threshold: float = 75.0
    min_word_overlap: float = 0.0
    reply_matching_algorithm: str = "levenshtein"
    reply_matching_threshold: float = 80.0
    follow_up: bool = False
    follow_up_timeout: float = 4.0
    follow_up_max_turns: int = 5
    follow_up_tone: str = "info"
    post_dispatch_cooldown_ms: int = 800
    min_cmd_words: int = 1
    dispatch_timeout: float = 90.0
    call_tone: bool = True


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
    history_file: str = "conf/history.jsonl"


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
class DisplayConfig:
    enabled: bool = False
    backend: str = "auto"  # auto | bridge | gpio | mock | i2c
    transport: str = "unix"  # auto | subprocess | unix | tcp
    matrix_brightness: int = 50
    led_brightness: int = 50
    i2c_bus: int = 1
    i2c_address: int = 0x3C
    i2c_width: int = 128
    i2c_height: int = 64


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
class SecretsConfig:
    livekit: LiveKitSecretsConfig = field(default_factory=LiveKitSecretsConfig)
    telegram: TelegramSecretsConfig = field(default_factory=TelegramSecretsConfig)
    llm_host: str | None = None
    llm_api_key: str | None = None
    mqtt: MQTTSecretsConfig = field(default_factory=MQTTSecretsConfig)


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


@dataclass
class ActionsData:
    triggers: list[Trigger] = field(default_factory=list)


@dataclass
class ActionsConfig:
    wake_words: list[str]  # flat list of wake phrases (all variants)
    triggers: list[Trigger]  # all triggers flat (with_wake=True and False)
    # Convenience subset: triggers with with_wake=False. Kept for backward compat
    # with code that reads config.direct_triggers.
    direct_triggers: list[Trigger] = field(default_factory=list)
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
    dump_triggers_dir: str | None = None


# ---------------------------------------------------------------------------
# Primitive parsers (actions, triggers)
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

        params = dict(a.get("params", {}))
        for k, v in a.items():
            if k not in ("type", "on_reply", "on_else", "params"):
                params[k] = v
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

        raw_actions = t.get("actions")
        if not isinstance(raw_actions, list):
            raise ConfigError(f"config:{path_prefix}[{i}] 'actions' must be a list")
        actions = _parse_actions(raw_actions, f"{path_prefix}[{i}]")

        # --- commands ---
        # New: commands: ["phrase1", "phrase2"]
        # Legacy: phrase: "..." + aliases: [...]
        raw_commands = t.get("commands")
        phrase = t.get("phrase")
        raw_aliases = t.get("aliases", [])
        if not isinstance(raw_aliases, list):
            raise ConfigError(f"config:{path_prefix}[{i}].aliases must be a list")
        aliases = [str(a) for a in raw_aliases if a]

        if raw_commands is not None:
            if not isinstance(raw_commands, list):
                raise ConfigError(f"config:{path_prefix}[{i}].commands must be a list")
            commands = [str(c) for c in raw_commands if c]
            if phrase:
                logger.warning(
                    "%s[%d]: 'phrase' ignored when 'commands' is present",
                    path_prefix,
                    i,
                )
        elif phrase:
            if not isinstance(phrase, str):
                raise ConfigError(
                    f"config:{path_prefix}[{i}] 'phrase' must be a string"
                )
            commands = [phrase] + aliases
            if aliases:
                logger.debug(
                    "%s[%d]: legacy 'phrase'+'aliases' folded into commands",
                    path_prefix,
                    i,
                )
        else:
            raise ConfigError(
                f"config:{path_prefix}[{i}] missing 'commands' list (or legacy 'phrase')"
            )

        if not commands:
            raise ConfigError(f"config:{path_prefix}[{i}] 'commands' must not be empty")

        # --- patterns ---
        raw_patterns = t.get("patterns", [])
        if not isinstance(raw_patterns, list):
            raise ConfigError(f"config:{path_prefix}[{i}].patterns must be a list")
        patterns = [str(p) for p in raw_patterns if p]

        # --- with_wake ---
        # New: with_wake: true/false
        # Legacy: wake_words: [] → with_wake=False; wake_words: [ids] → with_wake=True (scoping dropped)
        raw_with_wake = t.get("with_wake")
        raw_wake_words = t.get("wake_words")

        if raw_with_wake is not None:
            with_wake = bool(raw_with_wake)
            if raw_wake_words is not None:
                logger.warning(
                    "%s[%d]: 'wake_words' ignored when 'with_wake' is present",
                    path_prefix,
                    i,
                )
        elif raw_wake_words is not None:
            if not isinstance(raw_wake_words, list):
                raise ConfigError(
                    f"config:{path_prefix}[{i}].wake_words must be a list"
                )
            wake_words_val = [str(w) for w in raw_wake_words if w is not None]
            if len(wake_words_val) == 0:
                # wake_words: [] → fires without wake word
                with_wake = False
                logger.warning(
                    "%s[%d]: 'wake_words: []' is deprecated — use 'with_wake: false'",
                    path_prefix,
                    i,
                )
            else:
                # wake_words: [ids] → scoping dropped, becomes with_wake: true
                with_wake = True
                logger.warning(
                    "%s[%d]: 'wake_words: %r' scoping dropped — trigger fires after any wake word (with_wake: true)",
                    path_prefix,
                    i,
                    wake_words_val,
                )
        else:
            # Default: direct_match legacy key check
            if "direct_match" in t:
                logger.warning(
                    "%s[%d]: 'direct_match' is no longer supported — use 'with_wake: false'",
                    path_prefix,
                    i,
                )
                with_wake = False
            else:
                with_wake = True

        # --- follow_up, min_word_overlap ---
        raw_follow_up = t.get("follow_up")
        follow_up_val: bool | None = (
            None if raw_follow_up is None else bool(raw_follow_up)
        )
        raw_min_word_overlap = t.get("min_word_overlap")
        min_word_overlap_val: float | None = (
            float(raw_min_word_overlap) if raw_min_word_overlap is not None else None
        )

        # --- tag ---
        tag = str(t.get("tag", ""))

        # Populate compat phrase/aliases from commands
        compat_phrase = commands[0] if commands else ""
        compat_aliases = commands[1:] if len(commands) > 1 else []

        triggers.append(
            Trigger(
                commands=commands,
                actions=actions,
                patterns=patterns,
                with_wake=with_wake,
                follow_up=follow_up_val,
                min_word_overlap=min_word_overlap_val,
                tag=tag,
                phrase=compat_phrase,
                aliases=compat_aliases,
                wake_words=[str(w) for w in raw_wake_words if w is not None]
                if raw_wake_words is not None
                else None,
            )
        )
    return triggers


def _parse_wake_words_flat(raw_list: list[Any], source: str) -> list[str]:
    """Parse wake_words as a flat list of strings.

    Handles both the new flat format (list of strings) and the legacy group
    format (list of dicts with 'word'/'aliases' keys), emitting deprecation
    warnings for the latter.
    """
    phrases: list[str] = []
    seen: set[str] = set()

    for i, entry in enumerate(raw_list):
        if isinstance(entry, str):
            norm = entry.strip()
            if norm and norm not in seen:
                phrases.append(norm)
                seen.add(norm)
        elif isinstance(entry, dict):
            # Legacy group format
            word = entry.get("word")
            if not word or not isinstance(word, str):
                raise ConfigError(
                    f"{source}: wake_words[{i}] legacy group missing 'word' string"
                )
            logger.warning(
                "%s: wake_words[%d] uses legacy group format {word: %r, ...} — "
                "update to a flat string list",
                source,
                i,
                word,
            )
            raw_aliases = entry.get("aliases", [])
            if not isinstance(raw_aliases, list):
                raw_aliases = []
            for p in [word] + [str(a) for a in raw_aliases if a]:
                norm = p.strip()
                if norm and norm not in seen:
                    phrases.append(norm)
                    seen.add(norm)
        else:
            raise ConfigError(
                f"{source}: wake_words[{i}] must be a string or a mapping, "
                f"got {type(entry).__name__!r}"
            )

    return phrases


# Kept for backward compat (tests call this directly)
def _parse_wake_word_groups(raw_groups: list[Any], source: str) -> list[WakeWordGroup]:
    """Deprecated: use _parse_wake_words_flat instead."""
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


def _get_float(raw: dict, key: str, default: float) -> float:
    value = raw.get(key)
    return default if value is None else float(value)


def _get_int(raw: dict, key: str, default: int) -> int:
    value = raw.get(key)
    return default if value is None else int(value)


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

    output_volume = _get_float(raw, "output_volume", 0.5)
    if not (0.0 <= output_volume <= 1.0):
        raise ConfigError(
            f"'audio.output_volume' must be between 0.0 and 1.0, got {output_volume}"
        )

    input_gain = _get_float(raw, "input_gain", 1.0)
    if input_gain < 0.0:
        raise ConfigError(f"'audio.input_gain' must be >= 0.0, got {input_gain}")

    input_device = raw.get("input_device") or None
    output_device = raw.get("output_device") or None
    card_name_raw = raw.get("card_name")

    gst_raw = raw.get("gstreamer") or {}
    if not isinstance(gst_raw, dict):
        gst_raw = {}
    profiles_raw = gst_raw.get("profiles") or {}
    profiles: dict = {}
    if isinstance(profiles_raw, dict):
        for pname, pdict in profiles_raw.items():
            if isinstance(pdict, dict):
                profiles[str(pname)] = dict(pdict)
    gstreamer = GStreamerCaptureConfig(
        source=str(gst_raw.get("source", "pulsesrc")),
        noise_suppression=bool(gst_raw.get("noise_suppression", True)),
        noise_suppression_level=int(gst_raw.get("noise_suppression_level", 2)),
        agc=bool(gst_raw.get("agc", True)),
        agc_target_level_dbfs=int(gst_raw.get("agc_target_level_dbfs", -3)),
        agc_compression_gain_db=int(gst_raw.get("agc_compression_gain_db", 9)),
        high_pass_filter=bool(gst_raw.get("high_pass_filter", True)),
        compressor=bool(gst_raw.get("compressor", False)),
        compressor_threshold=float(gst_raw.get("compressor_threshold", 0.1)),
        compressor_ratio=float(gst_raw.get("compressor_ratio", 3.0)),
        profiles=profiles,
    )

    return AudioConfig(
        card_name=str(card_name_raw) if card_name_raw else None,
        input_device=str(input_device) if input_device else None,
        output_device=str(output_device) if output_device else None,
        output_volume=output_volume,
        input_gain=input_gain,
        sample_rates=sample_rates,
        post_playback_ms=int(raw.get("post_playback_ms", 100)),
        tone_preroll_ms=int(raw.get("tone_preroll_ms", 50)),
        webrtc=webrtc,
        gstreamer=gstreamer,
    )


def _parse_stt_config(raw: dict) -> STTConfig:
    # Warn on removed nested keys
    if "stage1" in raw:
        logger.warning(
            "stt.stage1 is removed — update to flat stt fields (backend, model_path, "
            "vad_silence_ms, …). See docs/stt-simple.md."
        )
    if "stage2" in raw:
        logger.warning(
            "stt.stage2 is removed — update to flat stt fields. See docs/stt-simple.md."
        )
    if raw.get("vosk_grammar") is not None:
        logger.warning(
            "stt.vosk_grammar is removed — free-vocabulary mode is always used."
        )
    if raw.get("keyword_spotter") is not None:
        logger.warning(
            "stt.keyword_spotter is removed — single-model design uses no KWS."
        )

    backend = str(raw.get("backend", "vosk"))
    if backend != "vosk":
        raise ConfigError(
            f"'stt.backend' must be 'vosk', got {backend!r}"
        )
    model_path_raw = raw.get("model_path")
    return STTConfig(
        backend=backend,
        model_path=str(model_path_raw) if model_path_raw else None,
        num_threads=_get_int(raw, "num_threads", 2),
        vad_silence_ms=_get_int(raw, "vad_silence_ms", 900),
        rms_threshold=_get_float(raw, "rms_threshold", 0.02),
        adaptive_rms=bool(raw.get("adaptive_rms", True)),
        adaptive_rms_margin=_get_float(raw, "adaptive_rms_margin", 0.01),
        min_speech_ms=_get_int(raw, "min_speech_ms", 200),
        wake_match_threshold=_get_float(raw, "wake_match_threshold", 0.5),
        mono_capture=bool(raw.get("mono_capture", False)),
        capture_backend=str(raw.get("capture_backend", "parec")),
    )


def _parse_tts_config(raw: dict) -> TTSConfig:
    backend = str(raw.get("backend", "piper"))
    return TTSConfig(
        backend=backend,
        voice=str(raw.get("voice", "it_IT-paola-medium")),
        preroll_ms=int(raw.get("preroll_ms", 100)),
    )


def _parse_recognition_config(raw: dict) -> RecognitionConfig:
    # Warn on removed keys
    _removed = (
        "mode",
        "partial_matching",
        "kws_one_breath",
        "partial_stability_ms",
        "partial_stability_reads",
        "command_timeout",
        "command_max_timeout",
    )
    for key in _removed:
        if raw.get(key) is not None:
            logger.warning(
                "recognition.%s is removed in the single-model design — ignored. "
                "Use 'recognition.wake_window' instead.",
                key,
            )

    algo = str(raw.get("matching_algorithm", "token_sort_ratio"))
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
        wake_window=_get_float(raw, "wake_window", 8.0),
        wake_tone=str(raw.get("wake_tone", "wake")),
        matching_algorithm=algo,
        matching_threshold=_get_float(raw, "matching_threshold", 75.0),
        min_word_overlap=_get_float(raw, "min_word_overlap", 0.0),
        reply_matching_algorithm=reply_algo,
        reply_matching_threshold=_get_float(raw, "reply_matching_threshold", 80.0),
        follow_up=bool(raw.get("follow_up", False)),
        follow_up_timeout=_get_float(raw, "follow_up_timeout", 4.0),
        follow_up_max_turns=_get_int(raw, "follow_up_max_turns", 5),
        follow_up_tone=str(raw.get("follow_up_tone", "info")),
        post_dispatch_cooldown_ms=_get_int(raw, "post_dispatch_cooldown_ms", 800),
        min_cmd_words=_get_int(raw, "min_cmd_words", 1),
        dispatch_timeout=_get_float(raw, "dispatch_timeout", 90.0),
        call_tone=bool(raw.get("call_tone", True)),
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
    raw_llm: dict,
    source: str,
    host_override: str | None = None,
    api_key_override: str | None = None,
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
    # api_key precedence: secrets.yaml llm_api_key > config.yaml llm.api_key
    api_key = api_key_override or str(raw_llm.get("api_key", ""))
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
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Multi-file action loading
# ---------------------------------------------------------------------------


def _parse_actions_file_raw(path: Path, source: str) -> dict:
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
    existing_wake_words: list[str] | None = None,
    system_file: str = "system.yaml",
) -> tuple[list[ActionEntry], ActionsData, list[str]]:
    """Load all .yaml files from dir_path; system_file first, rest alphabetically.

    Returns (on_startup_actions, merged_actions_data, extra_wake_words).
    on_startup is only read from system_file.
    extra_wake_words is the flat list of any wake phrases defined in action files.
    """
    if not dir_path.is_dir():
        logger.warning("Actions directory not found: %s", dir_path)
        return [], ActionsData(), []

    existing_wake_words = list(existing_wake_words or [])
    existing_set: set[str] = {w.lower().strip() for w in existing_wake_words}

    system_path = dir_path / system_file
    other_paths = sorted(p for p in dir_path.glob("*.yaml") if p.name != system_file)
    paths: list[tuple[Path, bool]] = []
    if system_path.exists():
        paths.append((system_path, True))
    for p in other_paths:
        paths.append((p, False))

    on_startup: list[ActionEntry] = []
    all_triggers: list[Trigger] = []
    extra_wake_words: list[str] = []

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

        # wake_words in action files: merge into flat list
        raw_ww = raw.get("wake_words")
        if raw_ww is not None:
            if not isinstance(raw_ww, list):
                logger.warning("%s: 'wake_words' must be a list — ignored", source)
            else:
                try:
                    new_phrases = _parse_wake_words_flat(raw_ww, source)
                except ConfigError as e:
                    logger.warning("%s: wake_words error — ignored: %s", source, e)
                    new_phrases = []
                added = 0
                for phrase in new_phrases:
                    norm = phrase.lower().strip()
                    if norm not in existing_set:
                        extra_wake_words.append(phrase)
                        existing_set.add(norm)
                        added += 1
                if added:
                    logger.info("%s: merged %d wake phrase(s)", source, added)

        # wake_triggers: removed key
        if raw.get("wake_triggers") is not None:
            logger.warning(
                "%s: 'wake_triggers' is no longer supported — "
                "use 'with_wake: false' on individual trigger entries instead",
                source,
            )

        # triggers: flat list
        raw_triggers = raw.get("triggers")
        if raw_triggers is not None:
            if not isinstance(raw_triggers, list):
                logger.warning("%s: 'triggers' must be a list — ignored", source)
            else:
                all_triggers.extend(_parse_triggers(raw_triggers, f"{source}:triggers"))

    return on_startup, ActionsData(triggers=all_triggers), extra_wake_words


# ---------------------------------------------------------------------------
# Secrets loader
# ---------------------------------------------------------------------------


def load_secrets(path: str | Path = "conf/secrets.yaml") -> SecretsConfig:
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
    llm_api_key = raw.get("llm_api_key") or None
    if llm_api_key:
        llm_api_key = str(llm_api_key)

    secrets = SecretsConfig(livekit=lk, telegram=tg, llm_host=llm_host, llm_api_key=llm_api_key, mqtt=mq)

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

    return _parse_actions_config(raw, source=str(p), secrets=secrets)


def _parse_actions_config(
    raw: dict,
    source: str = "config",
    secrets: SecretsConfig | None = None,
) -> ActionsConfig:
    """Parse a raw YAML dict into ActionsConfig."""
    # --- wake_words ---
    raw_wake_words = raw.get("wake_words")
    if raw_wake_words is not None and not isinstance(raw_wake_words, list):
        raise ConfigError(f"{source}: 'wake_words' must be a list if present")

    wake_words: list[str] = (
        _parse_wake_words_flat(raw_wake_words, source) if raw_wake_words else []
    )

    # --- sub-configs ---
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
        history_file=str(web_raw.get("history_file", "conf/history.jsonl")),
    )

    system_raw = raw.get("system") or {}
    if not isinstance(system_raw, dict):
        raise ConfigError(f"{source}: 'system' must be a mapping if present")
    system = _parse_system_config(system_raw)

    actions_raw = raw.get("actions") or {}
    if not isinstance(actions_raw, dict):
        raise ConfigError(f"{source}: 'actions' must be a mapping if present")
    actions_dir_cfg = _parse_actions_dir_config(actions_raw)

    # LLM
    llm: LLMConfig | None = None
    raw_llm = raw.get("llm")
    if raw_llm is not None:
        if not isinstance(raw_llm, dict):
            raise ConfigError(f"{source}: 'llm' must be a mapping if present")
        llm_host_override = (secrets.llm_host if secrets else None) or raw_llm.get(
            "host"
        )
        llm_api_key_override = (secrets.llm_api_key if secrets else None) or None
        if not llm_host_override:
            logger.warning(
                "%s: LLM disabled — 'llm_host' not set in conf/secrets.yaml or 'llm.host' in config",
                source,
            )
        else:
            try:
                llm = _parse_llm_config(
                    raw_llm,
                    source,
                    host_override=str(llm_host_override),
                    api_key_override=llm_api_key_override,
                )
            except ConfigError as e:
                logger.warning("LLM config error — LLM disabled: %s", e)

    # Display
    display: DisplayConfig | None = None
    raw_display = raw.get("display")
    if raw_display is not None:
        if not isinstance(raw_display, dict):
            raise ConfigError(f"{source}: 'display' must be a mapping if present")
        display = DisplayConfig(
            enabled=bool(raw_display.get("enabled", True)),
            backend=str(raw_display.get("backend", "auto")),
            transport=str(raw_display.get("transport", "unix")),
            matrix_brightness=int(raw_display.get("matrix_brightness", 50)),
            led_brightness=int(raw_display.get("led_brightness", 50)),
            i2c_bus=int(raw_display.get("i2c_bus", 1)),
            i2c_address=int(raw_display.get("i2c_address", "0x3C"), 16)
            if isinstance(raw_display.get("i2c_address"), str)
            else int(raw_display.get("i2c_address", 0x3C)),
            i2c_width=int(raw_display.get("i2c_width", 128)),
            i2c_height=int(raw_display.get("i2c_height", 64)),
        )

    # WebRTC env vars
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

    on_startup, actions_data, extra_wake_words = _load_actions_dir(
        actions_dir, existing_wake_words=wake_words
    )
    wake_words = wake_words + extra_wake_words

    if not wake_words:
        raise ConfigError(
            f"{source}: no wake words defined — add 'wake_words:' to "
            "config.yaml or to a conf/actions/*.yaml file"
        )

    # All triggers flat; direct_triggers = subset with with_wake=False
    all_triggers = actions_data.triggers
    direct_triggers = [t for t in all_triggers if not t.with_wake]

    dump_triggers_dir_raw = actions_raw.get("dump_triggers_dir")
    dump_triggers_dir = str(dump_triggers_dir_raw) if dump_triggers_dir_raw else None

    return ActionsConfig(
        wake_words=wake_words,
        triggers=all_triggers,
        direct_triggers=direct_triggers,
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
        dump_triggers_dir=dump_triggers_dir,
    )
