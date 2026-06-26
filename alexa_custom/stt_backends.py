from __future__ import annotations

import json
import logging
import os
import vosk
from abc import ABC, abstractmethod

from alexa_custom.config import (
    STTConfig,
    WakeWordGroup,
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
        # Grammar passed at construction is the "base" the recognizer returns to
        # after a phrase-restricted capture (see restore_base). For free-text it
        # is None; for the always-on grammar loop it is the wake/command grammar.
        self._base_grammar = grammar
        # Last parsed Result()/FinalResult() dict, kept so callers can read the
        # per-word acoustic confidences (result[].conf) alongside the text. Reset
        # only replaces the recognizer, never clears this — read it right after
        # text()/finalize().
        self._last_result: dict = {}
        self._rec = (
            vosk.KaldiRecognizer(model, sample_rate, grammar)
            if grammar
            else vosk.KaldiRecognizer(model, sample_rate)
        )
        self._rec.SetWords(True)

    @property
    def model(self) -> vosk.Model:
        return self._model

    @property
    def base_grammar(self) -> str | None:
        return self._base_grammar

    def accept_waveform(self, data: bytes) -> bool:
        return self._rec.AcceptWaveform(data)

    def text(self) -> str:
        self._last_result = json.loads(self._rec.Result())
        return self._last_result.get("text", "").strip()

    def partial_text(self) -> str:
        return json.loads(self._rec.PartialResult()).get("partial", "").strip()

    def finalize(self) -> str:
        """Flush the decoder (InputFinished) and return the final text.

        The base finalize() calls Result(), which does not flush Vosk's
        lookahead buffer, so the tail of an utterance can be dropped when the
        software VAD force-finalizes mid-command. FinalResult() flushes.
        """
        self._last_result = json.loads(self._rec.FinalResult())
        return self._last_result.get("text", "").strip()

    def last_words(self) -> list[dict]:
        """Per-word data (``word``/``conf``/timing) from the last text()/finalize()."""
        return self._last_result.get("result", [])

    def last_confidence(self, mode: str = "first", n_words: int | None = None) -> float:
        """Aggregate acoustic confidence of the last result.

        ``n_words`` limits aggregation to the first N words (e.g. the wake-word
        portion of a longer transcript); ``None`` uses every word.
        """
        words = self.last_words()
        if n_words is not None:
            words = words[:n_words]
        return _vosk_confidence(words, mode)

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

    def restore_base(self) -> None:
        """Return the recognizer to the grammar it was constructed with.

        Phrase-restricted captures (stt_capture) recreate() with a command
        grammar and call this in their ``finally`` so the always-on loop keeps
        its base grammar (free-text ``None``, or the wake/command grammar when
        ``stt.vosk_grammar`` is enabled) instead of being left free-text.
        """
        self.recreate(self._base_grammar)


def _load_model(model_path: str = _MODEL_PATH) -> vosk.Model:
    if not os.path.isdir(model_path):
        raise RuntimeError(
            f"Vosk model not found at {model_path!r}. Run 'serena-setup' to download it."
        )
    vosk.SetLogLevel(-1)
    return vosk.Model(model_path)


def _vosk_confidence(words: list[dict], mode: str = "first") -> float:
    """Aggregate per-token acoustic confidences from a Vosk ``result`` list.

    In grammar mode the recognizer is forced to snap every utterance onto the
    closest grammar phrase, so the *only* signal distinguishing a real match
    from one snapped out of background noise is the per-word ``conf``. ``mode``
    selects the aggregation: ``"min"`` (strictest — weakest word dominates),
    ``"mean"``, or ``"first"`` (default — the wake word is usually first).
    """
    if not words:
        return 0.0
    confs = [w.get("conf", 0.0) for w in words]
    if mode == "min":
        return min(confs)
    if mode == "mean":
        return sum(confs) / len(confs)
    return confs[0]  # "first" (default)


def _vosk_check_result(
    trigger_chunk: bytes,
    result: dict,
    alias_map: dict,
    confidence: float,
    confidence_mode: str,
    rms_threshold: float,
    wake_match_threshold: float = 0.5,
) -> tuple["WakeWordGroup | None", str]:
    """Gate a Vosk result on wake match + acoustic confidence + RMS.

    Returns ``(matched WakeWordGroup, inline_command)`` when the transcript
    matches a wake word *and* the wake-word portion clears the confidence and
    RMS thresholds; ``(None, "")`` otherwise. Used by the eval harness and as
    the shared confidence-gate primitive.

    ``wake_match_threshold`` is the fraction of the wake phrase's significant
    tokens that must appear in the transcript (mirrors ``stt.wake_match_threshold``
    in production): 0.5 fires on one of two words, 1.0 requires the full phrase.
    """
    # Imported lazily to avoid an import cycle (phonetics/gating import actions,
    # which is imported here at module load).
    from alexa_custom.stt_phonetics import (
        _approx_wake_match,
        _match_wake_word,
        _wake_token_count,
    )
    from alexa_custom.stt_gating import _rms_level

    text = result.get("text", "").strip()
    words = result.get("result", [])
    if not text:
        return None, ""

    group = _approx_wake_match(text, alias_map, threshold=wake_match_threshold)
    if group is None:
        return None, ""

    wake_phrases = [group.word] + group.aliases
    _, inline_cmd = _match_wake_word(text, wake_phrases, threshold=wake_match_threshold)

    # Confidence of the wake-word portion only (transcript minus the inline
    # command), so a low-confidence trailing command can't sink a clear wake.
    wake_word_count = _wake_token_count(text, inline_cmd)
    conf = _vosk_confidence(words[:wake_word_count], confidence_mode)
    logger.debug(
        "Wake result: %r conf=%.2f (mode=%s, thr=%.2f)",
        text,
        conf,
        confidence_mode,
        confidence,
    )

    if conf < confidence:
        return None, ""

    if rms_threshold > 0.0 and _rms_level(trigger_chunk) < rms_threshold:
        logger.debug("RMS gate rejected %r (quiet chunk)", text)
        return None, ""

    return group, inline_cmd


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


def get_stt_backend(
    cfg: STTConfig,
    keywords: list[str] | None = None,
    grammar: str | None = None,
) -> STTBackend:
    """Build a free-vocabulary STT backend from the given config.

    keywords is accepted but ignored for the single-model design (kept for
    call-site compatibility); grammar restricts the recognizer when set.
    """
    # vosk (default)
    vosk_path = cfg.model_path or _MODEL_PATH
    return VoskSTT(_load_model(vosk_path), grammar=grammar)
