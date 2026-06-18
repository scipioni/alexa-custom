from __future__ import annotations

import json
import logging
import os
import numpy as np
import vosk
from abc import ABC, abstractmethod

from alexa_custom.config import (
    STTConfig,
    STTStage1Config,
    STTStage2Config,
    WakeWordGroup,
    Trigger,
)

from alexa_custom.actions import normalize_text

logger = logging.getLogger(__name__)

_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "models/it")


class STTBackend(ABC):
    @abstractmethod
    def accept_waveform(self, data: bytes) -> bool:
        pass

    @abstractmethod
    def text(self) -> str:
        pass

    @abstractmethod
    def partial_text(self) -> str:
        pass

    @abstractmethod
    def reset(self) -> None:
        pass

    def finalize(self) -> str:
        """Force-complete the current utterance and return recognized text."""
        return self.text()


class VoskSTT(STTBackend):
    def __init__(
        self, model: vosk.Model, sample_rate: int = 16000, grammar: str | None = None
    ):
        self._model = model
        self._sample_rate = sample_rate
        self._grammar = grammar
        self._rec = (
            vosk.KaldiRecognizer(model, sample_rate, grammar)
            if grammar
            else vosk.KaldiRecognizer(model, sample_rate)
        )
        self._rec.SetWords(True)

    @property
    def model(self) -> vosk.Model:
        return self._model

    def accept_waveform(self, data: bytes) -> bool:
        return self._rec.AcceptWaveform(data)

    def text(self) -> str:
        return json.loads(self._rec.Result()).get("text", "").strip()

    def partial_text(self) -> str:
        return json.loads(self._rec.PartialResult()).get("partial", "").strip()

    def finalize(self) -> str:
        """Flush the decoder (InputFinished) and return the final text.

        The base finalize() calls Result(), which does not flush Vosk's
        lookahead buffer, so the tail of an utterance can be dropped when the
        software VAD force-finalizes mid-command. FinalResult() flushes.
        """
        return json.loads(self._rec.FinalResult()).get("text", "").strip()

    def reset(self) -> None:
        self._rec.Reset()

    def recreate(self, grammar: str | None = None) -> None:
        if grammar != self._grammar:
            self._grammar = grammar
            self._rec = (
                vosk.KaldiRecognizer(self._model, self._sample_rate, grammar)
                if grammar
                else vosk.KaldiRecognizer(self._model, self._sample_rate)
            )
            self._rec.SetWords(True)


def _load_model(model_path: str = _MODEL_PATH) -> vosk.Model:
    if not os.path.isdir(model_path):
        raise RuntimeError(
            f"Vosk model not found at {model_path!r}. Run 'alexa-setup' to download it."
        )
    vosk.SetLogLevel(-1)
    return vosk.Model(model_path)


def _phrases_to_grammar(phrases: list[str], label: str = "grammar") -> str:
    """Convert a list of phrases to a Vosk grammar JSON string.

    ``label`` names the consumer (e.g. ``"stage-1"`` / ``"stage-2"``) so the
    log line identifies exactly which recognizer the tokens belong to.
    """
    normalized = []
    for p in phrases:
        norm = normalize_text(p)
        if norm:
            normalized.append(norm)
    normalized = sorted(list(set(normalized)))
    grammar_tokens = normalized + ["[unk]"]
    logger.info(
        "%s grammar: %d tokens %s",
        label,
        len(grammar_tokens),
        grammar_tokens,
    )
    return json.dumps(grammar_tokens)


def _grammar_json(groups: list[WakeWordGroup], label: str = "grammar") -> str:
    phrases = [p for g in groups for p in [g.word] + g.aliases]
    return _phrases_to_grammar(phrases, label=label)


def _grammar_json_all(
    wake_words: list[WakeWordGroup],
    triggers: list["Trigger"],
    direct_triggers: list["Trigger"] | None = None,
    include_wake_gated: bool = True,
    label: str = "grammar",
) -> str:
    """Build a grammar string encompassing wake words and action triggers.

    ``include_wake_gated`` controls whether command phrases that only fire
    *after* a wake word (per-group scoped triggers and global triggers) are
    injected. These are needed in stage-1 only to support single-breath
    "wake + command" partial matching; with ``partial_matching`` disabled they
    serve no purpose in stage-1 and only widen the false-positive surface, so
    pass ``False`` to keep the grammar to wake words + direct-match triggers.
    """
    phrases = []
    # Add wake words and (only when wake-gated phrases are wanted) their
    # scoped triggers
    for g in wake_words:
        phrases.append(g.word)
        phrases.extend(g.aliases)
        if include_wake_gated:
            for t in g.triggers:
                phrases.append(t.phrase)
                phrases.extend(t.aliases)

    # Add global triggers (active after any wake word)
    if include_wake_gated:
        for t in triggers:
            phrases.append(t.phrase)
            phrases.extend(t.aliases)

    # Add direct-match triggers (wake_words: []) — these fire from stage-1
    # without a wake word, so they are always required in the grammar.
    for t in direct_triggers or []:
        phrases.append(t.phrase)
        phrases.extend(t.aliases)

    phrases = list(set(phrases))
    return _phrases_to_grammar(phrases, label=label)


def get_stt_backend(
    cfg: STTConfig | STTStage1Config | STTStage2Config,
    keywords: list[str] | None = None,
    grammar: str | None = None,
) -> STTBackend:
    """Build a free-vocabulary STT backend from the given config.

    Accepts the new flat STTConfig or the legacy stage configs for backward compat.
    keywords and grammar are accepted but ignored for the single-model design
    (kept for call-site compatibility).
    """
    # vosk (default)
    vosk_path = cfg.model_path or _MODEL_PATH
    return VoskSTT(_load_model(vosk_path), grammar=grammar)
