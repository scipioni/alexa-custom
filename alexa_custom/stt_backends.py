from __future__ import annotations

import json
import logging
import os
import numpy as np
import vosk
from abc import ABC, abstractmethod

from alexa_custom.config import STTStage1Config, STTStage2Config, WakeWordGroup, Trigger

from alexa_custom.actions import normalize_text
from alexa_custom.stt_gating import _rms_level

logger = logging.getLogger(__name__)

_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "models/it")
_SHERPA_MODEL_PATH = os.environ.get("SHERPA_ONNX_PATH", "models/it/kroko_128l")


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


def _write_bpe_vocab(tokens_path: str) -> str:
    """Write a bpe.vocab temp file from tokens.txt for ssentencepiece Viterbi tokenization.

    Each token gets score = len(token)^2 (unicode char count).  The quadratic
    weighting ensures greedy longest-match behaviour: a 2-char token beats two
    1-char tokens (4 > 1+1), a 4-char token beats two 2-char tokens (16 > 4+4),
    etc.  This produces tokenization consistent with the BPE model's actual output.
    """
    import tempfile

    lines: list[str] = []
    try:
        with open(tokens_path) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    token = parts[0]
                    score = len(token) ** 2
                    lines.append(f"{token}\t{score}")
    except OSError as e:
        raise RuntimeError(f"Cannot read tokens.txt at {tokens_path!r}: {e}") from e

    tf = tempfile.NamedTemporaryFile(
        mode="w", suffix=".vocab", delete=False, prefix="alexa_bpevocab_"
    )
    tf.write("\n".join(lines) + "\n")
    tf.close()
    return tf.name


class SherpaOnnxSTT(STTBackend):
    def __init__(
        self,
        model_dir: str = _SHERPA_MODEL_PATH,
        hotwords: list[str] | None = None,
        hotwords_score: float = 1.5,
    ):
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

        model_onnx = os.path.join(model_dir, "model.onnx")

        # Build hotwords temp file using modeling_unit="bpe" so Sherpa's ssentencepiece
        # tokenizes each phrase word-by-word, adding ▁ boundaries and running Viterbi.
        # This avoids the cjkchar SplitUtf8+MergeCharactersIntoWords path which splits
        # off ▁ and re-merges ASCII letters into strings not found in the symbol table.
        self._hotwords_tmp: str | None = None
        self._bpe_vocab_tmp: str | None = None
        hotwords_file = ""
        bpe_vocab_file = ""
        if hotwords:
            kw_lines = [normalize_text(p) for p in hotwords if normalize_text(p)]
            if kw_lines:
                bpe_vocab_file = _write_bpe_vocab(tokens)
                self._bpe_vocab_tmp = bpe_vocab_file
                tf = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, prefix="alexa_hw_"
                )
                tf.write("\n".join(kw_lines) + "\n")
                tf.close()
                self._hotwords_tmp = tf.name
                hotwords_file = tf.name
                logger.info(
                    "sherpa-hotwords: %d phrases registered (score=%.1f)\n%s",
                    len(kw_lines),
                    hotwords_score,
                    "\n".join(f"  {p!r}" for p in sorted(kw_lines)),
                )

        # modified_beam_search is required when hotwords_file is provided.
        decoding_method = "modified_beam_search" if hotwords_file else "greedy_search"

        if os.path.exists(joiner) or os.path.exists(joiner_int8):
            self._delegate = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=tokens,
                encoder=encoder_int8 if os.path.exists(encoder_int8) else encoder,
                decoder=decoder_int8 if os.path.exists(decoder_int8) else decoder,
                joiner=joiner_int8 if os.path.exists(joiner_int8) else joiner,
                num_threads=4,
                decoding_method=decoding_method,
                hotwords_file=hotwords_file,
                hotwords_score=hotwords_score if hotwords_file else 0.0,
                modeling_unit="bpe" if hotwords_file else "cjkchar",
                bpe_vocab=bpe_vocab_file if hotwords_file else "",
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
        self._last_partial: str = ""

    def __del__(self) -> None:
        for tmp in (self._hotwords_tmp, self._bpe_vocab_tmp):
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def accept_waveform(self, data: bytes) -> bool:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples**2)))
        self._stream.accept_waveform(sample_rate=16000, waveform=samples)
        while self._delegate.is_ready(self._stream):
            self._delegate.decode_stream(self._stream)
        endpoint = self._delegate.is_endpoint(self._stream)
        partial = self._delegate.get_result(self._stream)
        partial = partial.strip() if isinstance(partial, str) else partial.text.strip()
        if partial != self._last_partial:
            logger.debug("sherpa partial: %r  rms=%.4f", partial, rms)
            self._last_partial = partial
        if endpoint:
            logger.debug("sherpa endpoint fired: %r  rms=%.4f", partial, rms)
        return endpoint

    def text(self) -> str:
        result = self._delegate.get_result(self._stream)
        text = result.strip() if isinstance(result, str) else result.text.strip()
        logger.debug("sherpa text(): %r", text)
        return text

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
        logger.debug("sherpa finalize(): %r", text)
        self._last_partial = ""
        self._stream = self._delegate.create_stream()
        return text

    def reset(self) -> None:
        logger.debug("sherpa reset() last_partial=%r", self._last_partial)
        self._last_partial = ""
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
                    token = vocab[candidate]
                    # Mid-word positions must not use a word-boundary token
                    # (▁-prefixed). vocab[stripped] may resolve to the ▁ form
                    # when no standalone entry exists — using it mid-word injects
                    # a boundary marker that the acoustic model never emits there,
                    # causing the KWS to score the sequence at zero.
                    if not first and token.startswith(_BOUNDARY):
                        continue
                    word_tokens.append(token)
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
        kw_log: list[str] = []
        for kw in keywords:
            norm = normalize_text(kw)
            line = _tokenize_keyword(norm, vocab)
            if line:
                kw_lines.append(line)
                kw_log.append(f"{kw!r} -> [{line}]")
            else:
                logger.warning(
                    "KWS: keyword %r produced empty token sequence — skipped", kw
                )
        if not kw_lines:
            raise RuntimeError(
                "KWS: no valid keywords could be tokenised from the wake word list"
            )
        logger.info(
            "KWS keywords: %d registered\n%s",
            len(kw_lines),
            "\n".join(f"  {entry}" for entry in sorted(kw_log)),
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

        # Audio dump for debugging: set STT_AUDIO_DUMP=1 to record all audio
        # fed to the KWS to /tmp/kws_audio_dump.wav for offline inspection.
        _dump_path = os.environ.get("STT_AUDIO_DUMP")
        if _dump_path:
            import wave as _wave

            self._dump_wav = _wave.open(_dump_path, "wb")
            self._dump_wav.setnchannels(1)
            self._dump_wav.setsampwidth(2)
            self._dump_wav.setframerate(16000)
            logger.info("KWS audio dump enabled → %s", _dump_path)
        else:
            self._dump_wav = None

    def __del__(self) -> None:
        try:
            if hasattr(self, "_kw_file") and os.path.exists(self._kw_file.name):
                os.unlink(self._kw_file.name)
        except Exception:
            pass
        try:
            if getattr(self, "_dump_wav", None):
                self._dump_wav.close()
        except Exception:
            pass

    def accept_waveform(self, data: bytes) -> bool:
        if self._dump_wav:
            self._dump_wav.writeframes(data)
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
    cfg: STTStage1Config | STTStage2Config,
    keywords: list[str] | None = None,
    grammar: str | None = None,
) -> STTBackend:
    if cfg.backend == "sherpa-hotwords":
        model_path = cfg.model_path or _SHERPA_MODEL_PATH
        if not keywords:
            raise RuntimeError(
                "sherpa-hotwords requires at least one wake word in config"
            )
        return SherpaOnnxSTT(
            model_dir=model_path,
            hotwords=keywords,
            hotwords_score=cfg.hotwords_score if isinstance(cfg, STTStage1Config) else 1.5,
        )
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
    return VoskSTT(_load_model(vosk_path), grammar=grammar)


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
    confidence: float,
    confidence_mode: str,
    rms_threshold: float,
) -> tuple["WakeWordGroup | None", str]:
    """Process a Vosk stage-1 result and return (matched WakeWordGroup, inline_cmd)."""
    text = result.get("text", "").strip()
    words = result.get("result", [])

    from alexa_custom.stt import _extract_wake_command

    wake_match, inline_cmd = (
        _extract_wake_command(text, alias_map, fuzzy=False) if text else (None, "")
    )

    if not wake_match:
        return None, ""

    # We only care about the confidence of the wake word part.
    # The wake word text is text minus inline_cmd.
    wake_text_len = len(text) - len(inline_cmd)
    wake_text = text[:wake_text_len].strip()
    wake_word_count = len(wake_text.split())

    wake_words_data = words[:wake_word_count] if words else []
    conf = _vosk_confidence(wake_words_data, confidence_mode)

    logger.debug("Stage1 result: %r conf=%.2f (mode=%s)", text, conf, confidence_mode)

    if conf < confidence:
        return None, ""

    if _rms_level(trigger_chunk) < rms_threshold:
        logger.debug("Stage1 RMS gate rejected %r (quiet chunk)", text)
        return None, ""

    return wake_match, inline_cmd
