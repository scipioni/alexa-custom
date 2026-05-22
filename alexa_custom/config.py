from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass
class ActionEntry:
    type: str
    params: dict[str, Any] = field(default_factory=dict)


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
    recognition_mode: str = "two-stage"
    wake_confidence: float = 0.75


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

    wake_words = raw.get("wake_words")
    if not wake_words or not isinstance(wake_words, list) or len(wake_words) == 0:
        raise ConfigError("actions.yaml: 'wake_words' must be a non-empty list")

    command_timeout = float(raw.get("command_timeout", 3.0))

    recognition_mode = str(raw.get("recognition_mode", "two-stage"))
    if recognition_mode not in _VALID_MODES:
        raise ConfigError(
            f"actions.yaml: 'recognition_mode' must be one of {sorted(_VALID_MODES)}, got {recognition_mode!r}"
        )

    wake_confidence = float(raw.get("wake_confidence", 0.75))

    raw_triggers = raw.get("triggers")
    if not isinstance(raw_triggers, list):
        raise ConfigError("actions.yaml: 'triggers' must be a list")

    triggers: list[Trigger] = []
    for i, t in enumerate(raw_triggers):
        if not isinstance(t, dict):
            raise ConfigError(f"actions.yaml: triggers[{i}] must be a mapping")
        phrase = t.get("phrase")
        if not phrase or not isinstance(phrase, str):
            raise ConfigError(f"actions.yaml: triggers[{i}] missing 'phrase' string")
        raw_actions = t.get("actions")
        if not isinstance(raw_actions, list):
            raise ConfigError(f"actions.yaml: triggers[{i}] 'actions' must be a list")

        actions: list[ActionEntry] = []
        for j, a in enumerate(raw_actions):
            if not isinstance(a, dict):
                raise ConfigError(
                    f"actions.yaml: triggers[{i}].actions[{j}] must be a mapping"
                )
            action_type = a.get("type")
            if not action_type or not isinstance(action_type, str):
                raise ConfigError(
                    f"actions.yaml: triggers[{i}].actions[{j}] missing 'type' string"
                )
            params = {k: v for k, v in a.items() if k != "type"}
            actions.append(ActionEntry(type=action_type, params=params))

        triggers.append(Trigger(phrase=phrase, actions=actions))

    return ActionsConfig(
        wake_words=[str(w) for w in wake_words],
        command_timeout=command_timeout,
        triggers=triggers,
        recognition_mode=recognition_mode,
        wake_confidence=wake_confidence,
    )
