from __future__ import annotations

import json
import logging
import os
import numpy as np
import vosk
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alexa_custom.config import STTStage1Config, STTStage2Config, WakeWordGroup

from alexa_custom.actions import normalize_text
from alexa_custom.stt_gating import _rms_level

logger = logging.getLogger(__name__)

_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "models/it")
_SHERPA_MODEL_PATH = os.environ.get("SHERPA_ONNX_PATH", "models/sherpa-onnx")


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

    @property
    def model(self) -> vosk.Model:
        return self._model

    def accept_waveform(self, data: bytes) -> bool:
        return self._rec.AcceptWaveform(data)

    def text(self) -> str:
        return json.loads(self._rec.Result()).get("text", "").strip()

    def partial_text(self) -> str:
        return json.loads(self._rec.PartialResult()).get("partial", "").strip()

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


class SherpaOnnxSTT(STTBackend):
    def __init__(self, model_dir: str = _SHERPA_MODEL_PATH):
        import sherpa_onnx

        if not os.path.isdir(model_dir):
            raise RuntimeError(
                f"sherpa-onnx model not found at {model_dir!r}. Run 'alexa-setup --sherpa-onnx' to download it."
            )
        tokens = os.path.join(model_dir, "tokens.txt")
        encoder = os.path.join(model_dir, "encoder.onnx")
        decoder = os.path.join(model_dir, "decoder.onnx")
        joiner = os.path.join(model_dir, "joiner.onnx")
        encoder_int8 = os.path.join(model_dir, "encoder.int8.onnx")
        decoder_int8 = os.path.join(model_dir, "decoder.int8.onnx")
        joiner_int8 = os.path.join(model_dir, "joiner.int8.onnx")

        model_onnx = os.path.join(model_dir, "model.onnx")

        if os.path.exists(joiner) or os.path.exists(joiner_int8):
            self._delegate = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=tokens,
                encoder=encoder_int8 if os.path.exists(encoder_int8) else encoder,
                decoder=decoder_int8 if os.path.exists(decoder_int8) else decoder,
                joiner=joiner_int8 if os.path.exists(joiner_int8) else joiner,
                num_threads=4,
                decoding_method="greedy_search",
                sample_rate=16000,
                feature_dim=80,
                provider="cpu",
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=2.4,
                rule2_min_trailing_silence=1.2,
                rule3_min_utterance_length=20,
            )
        elif os.path.exists(model_onnx):
            if hasattr(sherpa_onnx.OnlineRecognizer, "from_zipformer2_ctc"):
                self._delegate = sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(
                    tokens=tokens,
                    model=model_onnx,
                    num_threads=4,
                    sample_rate=16000,
                    feature_dim=80,
                    provider="cpu",
                    enable_endpoint_detection=True,
                    rule1_min_trailing_silence=2.4,
                    rule2_min_trailing_silence=1.2,
                    rule3_min_utterance_length=20,
                )
            else:
                logger.warning(
                    "sherpa-onnx: model.onnx found but from_zipformer2_ctc not available "
                    "in installed version — falling back to from_paraformer"
                )
                self._delegate = sherpa_onnx.OnlineRecognizer.from_paraformer(
                    tokens=tokens,
                    encoder=encoder,
                    decoder=decoder,
                )
        else:
            self._delegate = sherpa_onnx.OnlineRecognizer.from_paraformer(
                tokens=tokens,
                encoder=encoder,
                decoder=decoder,
            )
        self._stream = self._delegate.create_stream()

    def accept_waveform(self, data: bytes) -> bool:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        self._stream.accept_waveform(sample_rate=16000, waveform=samples)
        while self._delegate.is_ready(self._stream):
            self._delegate.decode_stream(self._stream)
        return self._delegate.is_endpoint(self._stream)

    def text(self) -> str:
        result = self._delegate.get_result(self._stream)
        return result.strip() if isinstance(result, str) else result.text.strip()

    def partial_text(self) -> str:
        result = self._delegate.get_result(self._stream)
        return result.strip() if isinstance(result, str) else result.text.strip()

    def finalize(self) -> str:
        """Force the transducer to emit its buffered output, then reset the stream."""
        try:
            self._stream.input_finished()
        except Exception:
            pass
        while self._delegate.is_ready(self._stream):
            self._delegate.decode_stream(self._stream)
        result = self._delegate.get_result(self._stream)
        text = result.strip() if isinstance(result, str) else result.text.strip()
        self._stream = self._delegate.create_stream()
        return text

    def reset(self) -> None:
        self._delegate.reset(self._stream)


def _load_token_vocab(tokens_path: str) -> dict[str, str]:
    """Read tokens.txt and return {symbol: token_string} for keyword tokenisation."""
    vocab: dict[str, str] = {}
    try:
        with open(tokens_path) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    sym = parts[0]
                    vocab[sym] = sym
                    stripped = sym.lstrip("▁")
                    if stripped and stripped != sym:
                        vocab.setdefault(stripped, sym)
    except OSError as e:
        logger.warning("Could not read tokens.txt at %r: %s", tokens_path, e)
    return vocab


def _tokenize_keyword(word: str, vocab: dict[str, str]) -> str:
    """Tokenize a keyword string using greedy longest-match against the model vocab."""
    _BOUNDARY = "▁"
    result_tokens: list[str] = []

    for w in word.split():
        remaining = w
        word_tokens: list[str] = []
        first = True
        while remaining:
            matched = False
            for length in range(len(remaining), 0, -1):
                candidate = remaining[:length]
                if first:
                    prefixed = _BOUNDARY + candidate
                    if prefixed in vocab:
                        word_tokens.append(vocab[prefixed])
                        remaining = remaining[length:]
                        matched = True
                        first = False
                        break
                if candidate in vocab:
                    word_tokens.append(vocab[candidate])
                    remaining = remaining[length:]
                    matched = True
                    first = False
                    break
            if not matched:
                logger.warning(
                    "KWS: character %r in %r not in model vocab — skipping",
                    remaining[0],
                    w,
                )
                remaining = remaining[1:]
                first = False
        result_tokens.extend(word_tokens)

    return " ".join(result_tokens)


class SherpaKeywordSpotter(STTBackend):
    """Stage-1 backend using sherpa_onnx.KeywordSpotter."""

    def __init__(
        self,
        model_dir: str,
        keywords: list[str],
        keywords_score: float = 1.0,
        keywords_threshold: float = 0.25,
    ) -> None:
        import sherpa_onnx
        import tempfile

        if not os.path.isdir(model_dir):
            raise RuntimeError(
                f"sherpa-onnx model not found at {model_dir!r}. Run 'alexa-setup --sherpa-onnx' to download it."
            )

        tokens = os.path.join(model_dir, "tokens.txt")
        encoder = os.path.join(model_dir, "encoder.onnx")
        decoder = os.path.join(model_dir, "decoder.onnx")
        joiner = os.path.join(model_dir, "joiner.onnx")
        encoder_int8 = os.path.join(model_dir, "encoder.int8.onnx")
        decoder_int8 = os.path.join(model_dir, "decoder.int8.onnx")
        joiner_int8 = os.path.join(model_dir, "joiner.int8.onnx")

        vocab = _load_token_vocab(tokens)
        kw_lines: list[str] = []
        for kw in keywords:
            line = _tokenize_keyword(normalize_text(kw), vocab)
            if line:
                kw_lines.append(line)
            else:
                logger.warning(
                    "KWS: keyword %r produced empty token sequence — skipped", kw
                )
        if not kw_lines:
            raise RuntimeError(
                "KWS: no valid keywords could be tokenised from the wake word list"
            )

        self._kw_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="alexa_kws_"
        )
        self._kw_file.write("\n".join(kw_lines) + "\n")
        self._kw_file.close()

        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=tokens,
            encoder=encoder_int8 if os.path.exists(encoder_int8) else encoder,
            decoder=decoder_int8 if os.path.exists(decoder_int8) else decoder,
            joiner=joiner_int8 if os.path.exists(joiner_int8) else joiner,
            keywords_file=self._kw_file.name,
            num_threads=2,
            sample_rate=16000,
            feature_dim=80,
            keywords_score=keywords_score,
            keywords_threshold=keywords_threshold,
            provider="cpu",
        )
        self._stream = self._spotter.create_stream()
        self._last_keyword: str = ""

    def __del__(self) -> None:
        try:
            if hasattr(self, "_kw_file") and os.path.exists(self._kw_file.name):
                os.unlink(self._kw_file.name)
        except Exception:
            pass

    def accept_waveform(self, data: bytes) -> bool:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        self._stream.accept_waveform(sample_rate=16000, waveform=samples)
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
        result = self._spotter.get_result(self._stream)
        keyword = (
            result.keyword.strip()
            if hasattr(result, "keyword")
            else str(result).strip()
        )
        if keyword:
            self._last_keyword = keyword
            self._spotter.reset_stream(self._stream)
            return True
        return False

    def text(self) -> str:
        return self._last_keyword

    def partial_text(self) -> str:
        return ""

    def reset(self) -> None:
        self._stream = self._spotter.create_stream()
        self._last_keyword = ""

    def finalize(self) -> str:
        return ""


def _load_model(model_path: str = _MODEL_PATH) -> vosk.Model:
    if not os.path.isdir(model_path):
        raise RuntimeError(
            f"Vosk model not found at {model_path!r}. Run 'alexa-setup' to download it."
        )
    vosk.SetLogLevel(-1)
    return vosk.Model(model_path)


def _phrases_to_grammar(phrases: list[str]) -> str:
    """Convert a list of phrases to a Vosk grammar JSON string."""
    return json.dumps(phrases + ["[unk]"])


def _grammar_json(
    groups: list[WakeWordGroup], confuser_set: set[str] | None = None
) -> str:
    phrases = [p for g in groups for p in [g.word] + g.aliases]
    if confuser_set:
        phrases = phrases + [c for c in sorted(confuser_set) if c not in phrases]
    return _phrases_to_grammar(phrases)


def get_stt_backend(
    cfg: STTStage1Config | STTStage2Config,
    keywords: list[str] | None = None,
) -> STTBackend:
    if cfg.backend == "sherpa-onnx":
        model_path = cfg.model_path or _SHERPA_MODEL_PATH
        if isinstance(cfg, STTStage1Config) and cfg.keyword_spotter:
            if not keywords:
                raise RuntimeError(
                    "keyword_spotter=true requires at least one wake word in config"
                )
            return SherpaKeywordSpotter(
                model_dir=model_path,
                keywords=keywords,
                keywords_score=cfg.keywords_score,
                keywords_threshold=cfg.keywords_threshold,
            )
        return SherpaOnnxSTT(model_path)
    vosk_path = cfg.model_path or _MODEL_PATH
    return VoskSTT(_load_model(vosk_path))


def _vosk_confidence(words: list[dict], mode: str) -> float:
    """Aggregate per-token confidences from a Vosk result according to ``mode``."""
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
    confuser_set: set,
    confidence: float,
    confidence_mode: str,
    rms_threshold: float,
) -> "WakeWordGroup | None":
    """Process a completed Vosk stage-1 result and return the matched WakeWordGroup or None."""
    text = result.get("text", "").strip()
    words = result.get("result", [])
    conf = _vosk_confidence(words, confidence_mode)
    logger.debug("Stage1 result: %r conf=%.2f (mode=%s)", text, conf, confidence_mode)
    norm_text = normalize_text(text)
    if norm_text in confuser_set:
        logger.debug("Stage1 confuser rejected: %r", norm_text)
        return None
    wake_match = alias_map.get(norm_text)
    if wake_match is None or conf < confidence:
        return None
    if _rms_level(trigger_chunk) < rms_threshold:
        logger.debug("Stage1 RMS gate rejected %r (quiet chunk)", text)
        return None
    return wake_match
