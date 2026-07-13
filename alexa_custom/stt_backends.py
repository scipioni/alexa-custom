from __future__ import annotations

import json
import logging
import os
import vosk
from abc import ABC, abstractmethod
from collections import deque

import numpy as np

from alexa_custom.config import (
    STTConfig,
    WakeWordGroup,
)

from alexa_custom.actions import normalize_text

logger = logging.getLogger(__name__)

_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "models/it")

# sherpa-onnx backend (Kroko Zipformer + Silero VAD) — see docs/asr-plan.md.
_SHERPA_ONNX_MODEL_PATH = os.environ.get(
    "SHERPA_ONNX_MODEL_PATH", "models/it/kroko_64l"
)
_SHERPA_ONNX_VAD_PATH = os.environ.get(
    "SILERO_VAD_MODEL_PATH", "models/vad/silero_vad.onnx"
)
_SHERPA_ONNX_SAMPLE_RATE = 16000
# Zipformer's own trailing right-context/lookahead requirement — see
# docs/asr-plan.md "Troncamento dell'ultima parola". Without this many samples
# of real (or, as a fallback, zero-padded) trailing audio before
# input_finished(), the last word(s) of an utterance get truncated.
_SHERPA_ONNX_RIGHT_CONTEXT_SAMPLES = int(0.66 * _SHERPA_ONNX_SAMPLE_RATE)
# Pre-roll budget in SAMPLES, never chunks: capture backends deliver anywhere
# from ~320 B to 4 KB per read (same lesson as the byte-budgeted trigger-dump
# buffer — see CLAUDE.md), so a chunk-count budget would shrink to ~60 ms on
# GStreamer's small buffers and clip the first phoneme. 200 ms covers Silero's
# 100 ms onset debounce plus detection latency (docs/asr-plan.md sizing).
_SHERPA_ONNX_PRE_ROLL_SAMPLES = int(0.2 * _SHERPA_ONNX_SAMPLE_RATE)


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


class SherpaOnnxSTT(STTBackend):
    """Kroko Zipformer streaming transducer (sherpa-onnx) with an internal
    Silero VAD gate.

    Endpoint timing is deliberately NOT owned by this backend — accept_waveform()
    always returns False, so stt.py's existing RMS-based vad_fire/finalize()
    stays the single, backend-agnostic endpoint mechanism (see design.md
    "Reuse the existing RMS-based endpoint loop"). Silero VAD here is purely a
    CPU-saving gate: skip feeding the (expensive) Zipformer encoder while no
    speech is detected, matching the whole point of the docs/asr-plan.md
    proposal. A short pre-roll ring buffer prevents losing the onset phoneme
    when VAD flips from silence to speech.
    """

    def __init__(
        self,
        model_dir: str,
        vad_model_path: str,
        num_threads: int = 2,
        vad_threshold: float = 0.5,
        vad_min_speech_ms: int = 100,
        vad_min_silence_ms: int = 400,
        sample_rate: int = _SHERPA_ONNX_SAMPLE_RATE,
    ):
        import sherpa_onnx

        self._sherpa_onnx = sherpa_onnx
        self._sample_rate = sample_rate

        self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=os.path.join(model_dir, "tokens.txt"),
            encoder=os.path.join(model_dir, "encoder.int8.onnx"),
            decoder=os.path.join(model_dir, "decoder.int8.onnx"),
            joiner=os.path.join(model_dir, "joiner.int8.onnx"),
            num_threads=num_threads,
            sample_rate=sample_rate,
            feature_dim=80,
            decoding_method="greedy_search",
            provider="cpu",
        )

        vad_config = sherpa_onnx.VadModelConfig()
        vad_config.silero_vad.model = vad_model_path
        vad_config.silero_vad.threshold = vad_threshold
        # Onset debounce. sherpa-onnx's own default (250ms) misses short
        # commands — see docs/asr-plan.md "Comandi brevi non rilevati".
        vad_config.silero_vad.min_speech_duration = vad_min_speech_ms / 1000.0
        vad_config.silero_vad.min_silence_duration = vad_min_silence_ms / 1000.0
        vad_config.silero_vad.window_size = 512
        vad_config.sample_rate = sample_rate
        self._vad = sherpa_onnx.VoiceActivityDetector(
            vad_config, buffer_size_in_seconds=10
        )

        self._stream = self._recognizer.create_stream()
        self._pre_roll: deque = deque()
        self._pre_roll_samples = 0
        self._was_speaking = False
        # Countdown of real trailing audio still owed to the encoder after
        # Silero flips off (Zipformer's right-context lookahead). Refilled on
        # every speech chunk; finalize() zero-pads whatever remains unfed.
        self._tail_remaining = 0

    def accept_waveform(self, data: bytes) -> bool:
        data = data[: len(data) & ~1]  # np.int16 needs an even byte count
        if not data:
            return False
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

        self._vad.accept_waveform(samples)
        while not self._vad.empty():
            self._vad.pop()

        speaking = self._vad.is_speech_detected()

        if speaking:
            if not self._was_speaking:
                for buffered in self._pre_roll:
                    self._stream.accept_waveform(self._sample_rate, buffered)
                self._pre_roll.clear()
                self._pre_roll_samples = 0
            self._stream.accept_waveform(self._sample_rate, samples)
            while self._recognizer.is_ready(self._stream):
                self._recognizer.decode_stream(self._stream)
            self._tail_remaining = _SHERPA_ONNX_RIGHT_CONTEXT_SAMPLES
        elif self._tail_remaining > 0:
            # Just past speech end: still inside the right-context window —
            # keep feeding real audio to the encoder (a quiet trailing
            # syllable Silero missed may still be in here; substituting
            # zeros would discard it).
            self._stream.accept_waveform(self._sample_rate, samples)
            while self._recognizer.is_ready(self._stream):
                self._recognizer.decode_stream(self._stream)
            self._tail_remaining -= len(samples)
        else:
            # Genuinely idle: skip feeding the encoder (the CPU-saving gate),
            # keep a sample-budgeted pre-roll for the next onset instead.
            self._pre_roll.append(samples)
            self._pre_roll_samples += len(samples)
            while (
                self._pre_roll_samples > _SHERPA_ONNX_PRE_ROLL_SAMPLES
                and len(self._pre_roll) > 1
            ):
                self._pre_roll_samples -= len(self._pre_roll.popleft())

        self._was_speaking = speaking
        return False

    def text(self) -> str:
        return self._recognizer.get_result(self._stream).strip()

    def partial_text(self) -> str:
        return self._recognizer.get_result(self._stream).strip()

    def finalize(self) -> str:
        if self._tail_remaining > 0:
            self._stream.accept_waveform(
                self._sample_rate,
                np.zeros(self._tail_remaining, dtype=np.float32),
            )
        self._stream.input_finished()
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
        text = self._recognizer.get_result(self._stream).strip()
        # A finished OnlineStream must never be fed again (sherpa-onnx can
        # abort), and not every caller resets afterwards — stt_capture's
        # window finalizes and hands the same backend straight back to the
        # always-on loop. Self-reset so the contract is safe by construction;
        # stt.py's own reset-after-finalize becomes a harmless no-op repeat.
        self.reset()
        return text

    def reset(self) -> None:
        self._stream = self._recognizer.create_stream()
        # Clear Silero's trigger/hangover state too — a reset during TTS-echo
        # drain must not leave the gate latched open on stale audio.
        self._vad.reset()
        self._was_speaking = False
        self._tail_remaining = 0
        self._pre_roll.clear()
        self._pre_roll_samples = 0


def _check_sherpa_onnx_files(model_dir: str, vad_model_path: str) -> None:
    required = [
        os.path.join(model_dir, f)
        for f in (
            "tokens.txt",
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
        )
    ]
    missing = [f for f in required if not os.path.isfile(f)]
    if missing:
        raise RuntimeError(
            f"sherpa-onnx model files missing: {missing}. "
            f"Run 'serena-setup --sherpa-onnx-model 64l' to download them."
        )
    if not os.path.isfile(vad_model_path):
        raise RuntimeError(
            f"Silero VAD model not found at {vad_model_path!r}. "
            f"Run 'serena-setup --sherpa-onnx-model 64l' to download it."
        )


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
    if cfg.backend == "sherpa-onnx":
        if grammar is not None:
            logger.warning(
                "stt.vosk_grammar has no effect with backend sherpa-onnx — "
                "the recognizer is always free-vocabulary"
            )
        model_dir = cfg.model_path or _SHERPA_ONNX_MODEL_PATH
        _check_sherpa_onnx_files(model_dir, _SHERPA_ONNX_VAD_PATH)
        try:
            return SherpaOnnxSTT(
                model_dir=model_dir,
                vad_model_path=_SHERPA_ONNX_VAD_PATH,
                num_threads=cfg.num_threads,
                vad_threshold=cfg.sherpa_vad_threshold,
                vad_min_speech_ms=cfg.sherpa_vad_min_speech_ms,
                vad_min_silence_ms=cfg.sherpa_vad_min_silence_ms,
            )
        except ModuleNotFoundError as e:
            raise RuntimeError("sherpa-onnx is not installed. Run: uv sync") from e

    # vosk (default)
    vosk_path = cfg.model_path or _MODEL_PATH
    return VoskSTT(_load_model(vosk_path), grammar=grammar)
