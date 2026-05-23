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


_VALID_MODES = {"two-stage", "single-stage"}


@dataclass
class ActionsConfig:
    wake_words: list[str]
    command_timeout: float
    triggers: list[Trigger]
    on_startup: list[ActionEntry] = field(default_factory=list)
    recognition_mode: str = "two-stage"
    wake_confidence: float = 0.75


def _parse_actions(raw_actions: list[Any], path_prefix: str) -> list[ActionEntry]:
    actions: list[ActionEntry] = []
    for i, a in enumerate(raw_actions):
        if not isinstance(a, dict):
            raise ConfigError(
                f"actions.yaml: {path_prefix}.actions[{i}] must be a mapping"
            )
        action_type = a.get("type")
        if not action_type or not isinstance(action_type, str):
            raise ConfigError(
                f"actions.yaml: {path_prefix}.actions[{i}] missing 'type' string"
            )

        on_reply: list[Trigger] = []
        raw_reply = a.get("on_reply")
        if raw_reply is not None:
            if not isinstance(raw_reply, list):
                raise ConfigError(
                    f"actions.yaml: {path_prefix}.actions[{i}].on_reply must be a list"
                )
            on_reply = _parse_triggers(
                raw_reply, f"{path_prefix}.actions[{i}].on_reply"
            )

        on_else: list[ActionEntry] = []
        raw_else = a.get("on_else")
        if raw_else is not None:
            if not isinstance(raw_else, list):
                raise ConfigError(
                    f"actions.yaml: {path_prefix}.actions[{i}].on_else must be a list"
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
            raise ConfigError(f"actions.yaml: {path_prefix}[{i}] must be a mapping")
        phrase = t.get("phrase")
        if not phrase or not isinstance(phrase, str):
            raise ConfigError(
                f"actions.yaml: {path_prefix}[{i}] missing 'phrase' string"
            )
        raw_actions = t.get("actions")
        if not isinstance(raw_actions, list):
            raise ConfigError(
                f"actions.yaml: {path_prefix}[{i}] 'actions' must be a list"
            )

        actions = _parse_actions(raw_actions, f"{path_prefix}[{i}]")
        triggers.append(Trigger(phrase=phrase, actions=actions))
    return triggers


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

    return _parse_actions_config(raw, source=str(p))


def load_actions_config_auto(base_dir: str | Path = ".") -> ActionsConfig | None:
    """Load config.yaml if present, else fall back to actions.yaml (with deprecation warning)."""
    base = Path(base_dir)
    config_yaml = base / "config.yaml"
    actions_yaml = base / "actions.yaml"

    if config_yaml.exists():
        return load_config(config_yaml)

    if actions_yaml.exists():
        logger.warning(
            "actions.yaml is deprecated — migrate to config.yaml. "
            "See config.yaml.example for the new format."
        )
        return load_actions_config(actions_yaml)

    return None


def _parse_actions_config(raw: dict, source: str = "config") -> ActionsConfig:
    """Parse a raw YAML dict (env: already stripped) into ActionsConfig."""
    wake_words = raw.get("wake_words")
    if not wake_words or not isinstance(wake_words, list) or len(wake_words) == 0:
        raise ConfigError(f"{source}: 'wake_words' must be a non-empty list")

    command_timeout = float(raw.get("command_timeout", 3.0))

    recognition_mode = str(raw.get("recognition_mode", "two-stage"))
    if recognition_mode not in _VALID_MODES:
        raise ConfigError(
            f"{source}: 'recognition_mode' must be one of {sorted(_VALID_MODES)}, got {recognition_mode!r}"
        )

    wake_confidence = float(raw.get("wake_confidence", 0.75))

    on_startup: list[ActionEntry] = []
    raw_startup = raw.get("on_startup")
    if raw_startup is not None:
        if not isinstance(raw_startup, list):
            raise ConfigError(f"{source}: 'on_startup' must be a list")
        on_startup = _parse_actions(raw_startup, "on_startup")

    raw_triggers = raw.get("triggers")
    if not isinstance(raw_triggers, list):
        raise ConfigError(f"{source}: 'triggers' must be a list")

    triggers = _parse_triggers(raw_triggers, "triggers")

    return ActionsConfig(
        wake_words=[str(w) for w in wake_words],
        command_timeout=command_timeout,
        triggers=triggers,
        on_startup=on_startup,
        recognition_mode=recognition_mode,
        wake_confidence=wake_confidence,
    )


def load_actions_config(path: str | Path = "actions.yaml") -> ActionsConfig | None:
    p = Path(path)
    if not p.exists():
        return None

    try:
        with p.open() as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"actions.yaml parse error: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError("actions.yaml must be a YAML mapping at the top level")

    return _parse_actions_config(raw, source="actions.yaml")
