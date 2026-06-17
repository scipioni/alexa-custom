from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import re
import unicodedata
from typing import Any, Awaitable, Callable, Coroutine, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from alexa_custom.mqtt import MQTTClient

from alexa_custom.config import ActionEntry, Trigger

from rapidfuzz import fuzz as _fuzz
from rapidfuzz.distance import Levenshtein as _lev

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ActionContext:
    """Carries all call-site dependencies for dispatch() / _run_action().

    Collapsing these into one object means future deadline / cancellation
    fields are a one-field change rather than a six-site edit.
    """

    telegram_client: TelegramClient
    livekit_connect_fn: Callable[[], Awaitable[None]] | None = None
    livekit_connected: bool = False
    listen_fn: Callable[..., Awaitable[str]] | None = None
    mqtt_client: MQTTClient | None = None
    on_stt_event: Callable[[str, dict], None] | None = None
    actions_config: object | None = None  # ActionsConfig, avoids circular import


_PUNCT_CHARS = "?!.,;:()[]{}#"


def normalize_text(text: str) -> str:
    """Lowercase, remove punctuation, and remove diacritics (e.g., 'sì' -> 'si')."""
    if not text:
        return ""
    text_clean = "".join(c for c in text if c not in _PUNCT_CHARS)
    nfd = unicodedata.normalize("NFD", text_clean.lower())
    stripped = "".join(c for c in nfd if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", stripped).strip()


def italian_phonetic(text: str) -> str:
    """Reduce Italian text to a rough phoneme representation for fuzzy matching.

    Applies normalize_text() first, then rewrites common Italian digraphs/trigraphs
    and geminate consonants so acoustically equivalent forms compare as equal.
    """
    t = normalize_text(text)
    # 1. Geminate consonants → single
    t = re.sub(r"([bcdfglmnprstvz])\1", r"\1", t)
    # 2. Trigraph gli → li
    t = t.replace("gli", "li")
    # 3. Digraph gn → n
    t = t.replace("gn", "n")
    # 4. sch before vowel → sk
    t = re.sub(r"sch([aeiou])", r"sk\1", t)
    # 5. sci/sce → si/se
    t = t.replace("sci", "si").replace("sce", "se")
    # 6. ch before e/i → k
    t = re.sub(r"ch([ei])", r"k\1", t)
    # 7. gh before e/i → g
    t = re.sub(r"gh([ei])", r"g\1", t)
    # 8. qu → k
    t = t.replace("qu", "k")
    return t


def _word_token_match(pw: str, tw: str) -> bool:
    """Return True if transcript word ``tw`` is an acoustic match for word ``pw``.

    Compares Italian phonetic forms (so ``che``/``ke`` etc. compare equal) and
    accepts only *prefix-anchored* relationships, which is how STT actually
    mangles words:
    - exact phonetic equality
    - ``pw`` is a phonetic prefix of ``tw``  → inflection ("accendi" → "accendimi")
    - ``tw`` is a phonetic prefix of ``pw``  → truncation ("galile" → "galileo"),
      but only when ``tw`` covers ≥70% of ``pw`` so short fragments ("gali") do
      not match a longer word.

    This is deliberately stricter than substring-anywhere matching: a fragment
    buried mid-word or in a suffix ("casa" inside "scocciacasa") does not match.
    """
    pp = italian_phonetic(pw)
    tp = italian_phonetic(tw)
    if not pp or not tp:
        return False
    if pp == tp:
        return True
    if len(pp) >= 3 and tp.startswith(pp):
        return True
    if len(tp) >= 3 and len(tp) >= len(pp) * 0.7 and pp.startswith(tp):
        return True
    return False


def _trigger_phrases(trigger: "Trigger") -> list[str]:
    """All recognizable phrases for a trigger.

    Single source of truth for both fuzzy matching (match_trigger_with_score)
    and Vosk grammar construction (handle_ask reply window). Keeping these in
    sync matters: if the grammar omits an alias the recognizer physically cannot
    emit it, so the alias would never match no matter how lenient the scorer is.
    """
    return (
        trigger.commands if trigger.commands else ([trigger.phrase] + trigger.aliases)
    )


class TelegramClient:
    def __init__(self) -> None:
        self._token: str | None = os.environ.get("TELEGRAM_BOT_TOKEN")

    async def send_message(self, chat_id: str, text: str) -> None:
        if not self._token:
            logger.error("TELEGRAM_BOT_TOKEN not set — telegram action skipped")
            return
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json={"chat_id": chat_id, "text": text})
                resp.raise_for_status()
        except Exception as e:
            logger.error(f"Telegram send_message failed: {e}")

    # Future: async def start_polling(self, handler) -> None: ...


_TRIGGER_THRESHOLD = 70.0


def get_similarity_score(a: str, b: str, algorithm: str) -> float:
    """Calculate a similarity score (0.0 - 100.0) between two strings based on algorithm."""
    if not a or not b:
        return 0.0
    if algorithm == "levenshtein":
        max_len = max(len(a), len(b))
        if max_len == 0:
            return 100.0
        return (1.0 - (_lev.distance(a, b) / max_len)) * 100.0
    elif algorithm == "ratio":
        return _fuzz.ratio(a, b)
    elif algorithm == "token_sort_ratio":
        # Order-independent but length-aware: sorts tokens then does a full-string
        # ratio. Unlike token_set_ratio it does NOT collapse to 100 when the
        # transcript is a subset of the phrase, so a single word ("sono") cannot
        # falsely match a longer command ("che ore sono").
        return _fuzz.token_sort_ratio(a, b)
    else:  # "token_set_ratio"
        return _fuzz.token_set_ratio(a, b)


def _match_glob_pattern(
    pattern: str,
    transcript: str,
    algorithm: str = "token_set_ratio",
    threshold: float = _TRIGGER_THRESHOLD,
) -> bool:
    """Fuzzy ordered-subsequence walk of a word-glob pattern against a transcript.

    Token semantics:
    - standalone ``*``  : matches zero or more transcript words (gap)
    - ``foo*``          : matches a transcript word whose phonetic form starts
                          with the phonetic prefix of ``foo``
    - literal token     : matches a transcript word above the phonetic similarity
                          threshold (via italian_phonetic + get_similarity_score)
    """
    p_tokens = pattern.split()
    t_tokens = [italian_phonetic(w) for w in transcript.split()]

    def _token_matches(p_tok: str, t_phon: str) -> bool:
        if p_tok.endswith("*"):
            prefix = italian_phonetic(p_tok[:-1])
            return t_phon.startswith(prefix)
        return (
            get_similarity_score(italian_phonetic(p_tok), t_phon, algorithm)
            >= threshold
        )

    # Recursive ordered-subsequence walk with memoisation.
    from functools import lru_cache

    @lru_cache(maxsize=None)
    def _walk(pi: int, ti: int) -> bool:
        # consumed all pattern tokens → matched
        if pi == len(p_tokens):
            return True
        tok = p_tokens[pi]
        if tok == "*":
            # gap: try consuming 0 … remaining transcript words
            for skip in range(ti, len(t_tokens) + 1):
                if _walk(pi + 1, skip):
                    return True
            return False
        # literal or glob token: find the next transcript word that satisfies it
        for ti2 in range(ti, len(t_tokens)):
            if _token_matches(tok, t_tokens[ti2]):
                if _walk(pi + 1, ti2 + 1):
                    return True
        return False

    return _walk(0, 0)


def _trigger_matches_patterns(
    trigger: "Trigger",
    transcript: str,
    algorithm: str = "token_set_ratio",
    threshold: float = _TRIGGER_THRESHOLD,
) -> bool:
    """Return True if any of the trigger's patterns match the transcript."""
    return any(
        _match_glob_pattern(p, transcript, algorithm, threshold)
        for p in trigger.patterns
    )


def match_trigger_with_score(
    transcript: str,
    triggers: list[Trigger],
    threshold: float = _TRIGGER_THRESHOLD,
    algorithm: str = "token_set_ratio",
    min_word_overlap: float = 0.0,
) -> tuple[Trigger | None, float]:
    # Pattern match is definitive: first trigger whose patterns match wins.
    for trigger in triggers:
        if trigger.patterns and _trigger_matches_patterns(
            trigger, transcript, algorithm, threshold
        ):
            logger.debug(f"Matched trigger '{trigger.phrase}' (glob pattern)")
            return trigger, 100.0

    # Fuzzy fallback: best phonetic similarity score above threshold.
    best: Trigger | None = None
    best_score = 0.0
    t_phon = italian_phonetic(transcript)
    _t_words: list[str] | None = None
    for trigger in triggers:
        phrases = _trigger_phrases(trigger)
        # Word-overlap guard. Each phrase's *content* words (phonetic length ≥ 3,
        # i.e. excluding stopwords like "la"/"di"/"che") are matched against the
        # transcript words via _word_token_match (phonetic, prefix-anchored —
        # tolerant of STT inflection/truncation). Two gates:
        #   - floor: at least one content word must appear. This kills
        #     token_set_ratio hits driven purely by shared stopwords, and is
        #     recall-safe because a genuine command always carries its content
        #     words. Phrases with no content words (e.g. "si") skip the floor
        #     and rely on the short-phrase exact-match guard below.
        #   - eff_overlap: optional stricter fraction (per-trigger override of
        #     the call-site global) for triggers that need tighter gating.
        eff_overlap = (
            trigger.min_word_overlap
            if trigger.min_word_overlap is not None
            else min_word_overlap
        )
        if _t_words is None:
            _t_words = transcript.split()
        overlap_ok = False
        for p in phrases:
            content = [
                w for w in normalize_text(p).split() if len(italian_phonetic(w)) >= 3
            ]
            if not content:
                overlap_ok = True  # short-only phrase: defer to exact-match guard
                break
            matched = sum(
                1 for w in content if any(_word_token_match(w, tw) for tw in _t_words)
            )
            if matched >= 1 and matched / len(content) >= eff_overlap:
                overlap_ok = True
                break
        if not overlap_ok:
            continue
        scores = []
        for p in phrases:
            p_phon = italian_phonetic(p)
            if len(p_phon) < 4:
                score = 100.0 if t_phon == p_phon else 0.0
            else:
                score = get_similarity_score(t_phon, p_phon, algorithm)
            scores.append(score)
        score = max(scores)
        if score > best_score:
            best_score = score
            best = trigger
    if best is not None and best_score >= threshold:
        logger.debug(f"Matched trigger '{best.phrase}' (score={best_score:.0f})")
        return best, best_score
    return None, best_score


def match_trigger(
    transcript: str,
    triggers: list[Trigger],
    threshold: float = _TRIGGER_THRESHOLD,
    algorithm: str = "token_set_ratio",
    min_word_overlap: float = 0.0,
) -> Trigger | None:
    trigger, _ = match_trigger_with_score(
        transcript, triggers, threshold, algorithm, min_word_overlap
    )
    return trigger


_dispatch_depth = 0
_MAX_DISPATCH_DEPTH = 10


async def dispatch(
    trigger: Trigger,
    ctx: ActionContext,
    *,
    wake_word: str | None = None,
    transcript: str | None = None,
) -> None:
    global _dispatch_depth
    _dispatch_depth += 1
    if _dispatch_depth > _MAX_DISPATCH_DEPTH:
        _dispatch_depth -= 1
        logger.warning(
            "Dispatch depth exceeded (%d) — breaking recursive chain",
            _dispatch_depth,
        )
        return
    try:
        for action in trigger.actions:
            await _run_action(action, ctx, wake_word=wake_word, transcript=transcript)
    finally:
        _dispatch_depth -= 1


class ActionRegistry:
    def __init__(self):
        self._handlers: dict[str, Callable] = {}

    def register(self, action_type: str):
        def decorator(func: Callable):
            self._handlers[action_type] = func
            return func

        return decorator

    async def execute(self, action_type: str, **kwargs) -> None:
        handler = self._handlers.get(action_type)
        if handler:
            await handler(**kwargs)
        else:
            logger.warning(f"Unknown action type '{action_type}' — skipping")


registry = ActionRegistry()


@registry.register("log")
async def handle_log(action: ActionEntry, **_):
    message = action.params.get("message", "(no message)")
    logger.info(f"[log action] {message}")


@registry.register("telegram")
async def handle_telegram(action: ActionEntry, telegram_client: TelegramClient, **_):
    chat_id = action.params.get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID", "")
    text = action.params.get("text", "")
    if not chat_id:
        logger.error(
            "telegram action: no chat_id in action or TELEGRAM_CHAT_ID env var"
        )
        return
    if "<room>" in text:
        from alexa_custom.client import browser_join_url

        text = text.replace("<room>", browser_join_url())
    await telegram_client.send_message(chat_id, text)


@registry.register("livekit_join")
async def handle_livekit_join(
    livekit_connected: bool,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    **_,
):
    if livekit_connected:
        logger.debug("livekit_join action: already connected, skipping")
        return
    if livekit_connect_fn is None:
        logger.warning("livekit_join action: no connect function available")
        return
    await livekit_connect_fn()


_CMD_RE = re.compile(r"\$\(([^)]+)\)")


async def _render_text(text: str) -> str:
    """Expand $(shell command) placeholders in text."""

    async def _run(cmd: str) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return stdout.decode().strip()
        except Exception as e:
            logger.warning("say template command failed %r: %s", cmd, e)
            return ""

    matches = _CMD_RE.findall(text)
    if not matches:
        return text

    results = await asyncio.gather(*(_run(m) for m in matches))
    result = text
    for match, value in zip(matches, results):
        result = result.replace(f"$({match})", value, 1)
    return result


@registry.register("say")
async def handle_say(action: ActionEntry, mqtt_client: MQTTClient | None, **_):
    from alexa_custom.tts import get_engine

    text = await _render_text(action.params.get("text", ""))
    lang = action.params.get("lang", "it-IT")
    if text:
        if mqtt_client:
            await mqtt_client.publish(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                "speaking",
            )
        await asyncio.to_thread(get_engine().say, text, lang)
        if mqtt_client:
            await mqtt_client.publish(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle"
            )


@registry.register("ask")
async def handle_ask(
    action: ActionEntry,
    ctx: ActionContext,
    listen_fn: Callable[..., Coroutine[Any, Any, str]] | None,
    mqtt_client: MQTTClient | None,
    on_stt_event: Callable[[str, dict], None] | None,
    actions_config=None,
    wake_word: str | None = None,
    **_,
):
    from alexa_custom.tts import get_engine

    text = action.params.get("text", "")
    lang = action.params.get("lang", "it-IT")
    timeout = float(action.params.get("timeout", 5.0))

    if listen_fn is None:
        logger.warning("ask action: no listen_fn available")
        if text:
            if mqtt_client:
                await mqtt_client.publish(
                    f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                    "speaking",
                )
            await asyncio.to_thread(get_engine().say, text, lang)
        if mqtt_client:
            await mqtt_client.publish(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle"
            )
        return

    # Use constrained grammar if triggers are defined to improve accuracy (e.g., 'si' vs 'se').
    # Must include every command/alias the matcher accepts — a Vosk grammar
    # restricts what the recognizer can emit, so an omitted alias is unmatchable.
    phrases = [p for t in action.on_reply for p in _trigger_phrases(t)]

    if text and mqtt_client:
        await mqtt_client.publish(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "speaking"
        )

    # Run listen in parallel with TTS: capture discards frames in-flight while
    # the playback gate is set (no pipe backlog accumulation), then restarts
    # the `timeout` countdown when the gate drops. This closes the dead-window
    # where a fast reply right after the question used to be dropped.
    listen_task = asyncio.create_task(
        listen_fn(
            timeout,
            flush_ms=0,
            phrases=phrases if phrases else None,
            start_after_playback=bool(text),
        )
    )

    if text:
        await asyncio.to_thread(get_engine().say, text, lang)

    if mqtt_client:
        await mqtt_client.publish(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "listening"
        )

    transcript = await listen_task
    if transcript:
        algo = "levenshtein"
        threshold = 80.0
        if actions_config is not None:
            algo = actions_config.recognition.reply_matching_algorithm
            threshold = actions_config.recognition.reply_matching_threshold

        reply_trigger, reply_score = match_trigger_with_score(
            transcript,
            action.on_reply,
            threshold=threshold,
            algorithm=algo,
        )
        if reply_trigger:
            logger.info(f"Matched reply trigger: '{reply_trigger.phrase}'")
            if on_stt_event:
                on_stt_event(
                    "matched",
                    {
                        "transcript": transcript,
                        # Same schema as command matches in stt.py (the web
                        # dashboard reads "phrase"); a reply is a match too.
                        "phrase": reply_trigger.commands[0]
                        if reply_trigger.commands
                        else reply_trigger.phrase,
                        "score": reply_score,
                        "actions": [
                            {"type": a.type, "params": a.params}
                            for a in reply_trigger.actions
                        ],
                    },
                )
            await dispatch(
                reply_trigger,
                ctx,
                wake_word=wake_word,
                transcript=transcript,
            )
        elif action.on_else:
            logger.info(f"No reply trigger matched '{transcript}', running on_else")
            if on_stt_event:
                on_stt_event(
                    "nomatch", {"transcript": transcript, "score": reply_score}
                )
            for else_action in action.on_else:
                await _run_action(else_action, ctx, wake_word=wake_word)
        else:
            logger.info(f"No reply trigger matched '{transcript}' and no on_else")
            if on_stt_event:
                on_stt_event(
                    "nomatch", {"transcript": transcript, "score": reply_score}
                )
            from alexa_custom.audio import play_timeout_beep

            await asyncio.to_thread(play_timeout_beep)
    elif action.on_else:
        logger.info("No transcript received (timeout), running on_else")
        for else_action in action.on_else:
            await _run_action(else_action, ctx, wake_word=wake_word)
    else:
        logger.info("No transcript received (timeout) and no on_else")
        if on_stt_event:
            on_stt_event("nomatch", {"transcript": ""})
        from alexa_custom.audio import play_timeout_beep

        await asyncio.to_thread(play_timeout_beep)

    if mqtt_client:
        await mqtt_client.publish(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle"
        )


@registry.register("tone")
async def handle_tone(action: ActionEntry, **_):
    from alexa_custom.audio import play_tone

    name = action.params.get("name", "info")
    await asyncio.to_thread(play_tone, name)


@registry.register("set_volume")
async def handle_set_volume(action: ActionEntry, **_):
    from alexa_custom.audio import play_tone
    from alexa_custom.audio_hw import (
        get_output_volume,
        pulse_session,
        save_volume_config,
        set_output_volume,
    )

    mode = action.params.get("mode", "absolute")
    step = float(action.params.get("step", 0.1))
    value = float(action.params.get("value", 0.5))

    current = get_output_volume()
    if mode == "up":
        new_vol = min(1.0, current + step)
    elif mode == "down":
        new_vol = max(0.0, current - step)
    else:
        new_vol = max(0.0, min(1.0, value))

    if abs(new_vol - current) < 0.001:
        return

    with pulse_session("alexa-volume") as pulse:
        set_output_volume(pulse, None, new_vol)
    save_volume_config(new_vol)
    await asyncio.to_thread(play_tone, "info")


@registry.register("set_volume_from_transcript")
async def handle_set_volume_from_transcript(transcript: str | None = None, **_):
    from alexa_custom.audio import play_tone
    from alexa_custom.audio_hw import (
        pulse_session,
        save_volume_config,
        set_output_volume,
    )
    from alexa_custom.number_parser import parse_percentage

    if not transcript:
        logger.debug("set_volume_from_transcript: no transcript, skipping")
        return

    value = parse_percentage(transcript)
    if value is None:
        logger.debug(
            "set_volume_from_transcript: no percentage found in '%s', skipping",
            transcript,
        )
        return

    with pulse_session("alexa-volume") as pulse:
        set_output_volume(pulse, None, value)
    save_volume_config(value)
    logger.info("Set volume to %.0f%% via '%s'", value * 100, transcript)
    await asyncio.to_thread(play_tone, "info")


@registry.register("shell")
async def handle_shell(action: ActionEntry, **_):
    command = action.params.get("command", "")
    if not command:
        logger.error("shell action: no command provided")
        return

    logger.info(f"Executing shell command: {command}")
    try:
        process = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(
                f"Shell command failed (exit {process.returncode}): {stderr.decode().strip()}"
            )
        else:
            logger.info(f"Shell command output: {stdout.decode().strip()}")
    except Exception as e:
        logger.error(f"Failed to execute shell command: {e}")


@registry.register("mqtt_publish")
async def handle_mqtt_publish(action: ActionEntry, mqtt_client: MQTTClient | None, **_):
    if mqtt_client is None:
        logger.warning("mqtt_publish action: no mqtt_client available")
        return
    topic = action.params.get("topic")
    payload = action.params.get("payload", "")
    retain = action.params.get("retain", False)
    if not topic:
        logger.error("mqtt_publish action: no topic provided")
        return
    await mqtt_client.publish(topic, payload, retain=retain)


@registry.register("llm_chat")
async def handle_llm_chat(
    action: ActionEntry,
    listen_fn: Callable[..., Coroutine[Any, Any, str]] | None,
    mqtt_client: MQTTClient | None,
    on_stt_event: Callable[[str, dict], None] | None = None,
    actions_config=None,
    wake_word: str | None = None,
    transcript: str | None = None,
    **_,
) -> None:
    from alexa_custom.llm import _UNREACHABLE, get_engine
    from alexa_custom.tts import get_engine as get_tts

    if actions_config is None or actions_config.llm is None:
        logger.warning("llm_chat action: LLM not configured — skipping")
        return
    if listen_fn is None:
        logger.warning("llm_chat action: no listen_fn available — skipping")
        return

    cfg = actions_config.llm
    lang = "it-IT"
    if wake_word and actions_config.wake_words:
        for grp in actions_config.wake_words:
            if grp.word == wake_word:
                lang = grp.lang
                break

    system_prompt_override = action.params.get("system_prompt")
    import dataclasses

    if system_prompt_override:
        cfg = dataclasses.replace(cfg, system_prompt=system_prompt_override)

    engine = get_engine(cfg, lang)

    from alexa_custom.audio import play_tone

    await asyncio.to_thread(play_tone, "info")

    # Use the command that triggered this action as the first turn so the LLM
    # has context about what the user said.  Subsequent turns come from listen_fn.
    _pending = transcript or ""
    try:
        for _ in range(cfg.context_turns):
            if _pending:
                turn_text = _pending
                _pending = ""
            else:
                if mqtt_client:
                    await mqtt_client.publish(
                        f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                        "listening",
                    )
                turn_text = (await listen_fn(10.0, flush_ms=300)).strip()
            if not turn_text:
                break
            from alexa_custom.llm import is_exit_phrase

            if is_exit_phrase(turn_text, cfg.exit_phrases):
                engine.reset()
                break
            if on_stt_event:
                on_stt_event("llm_thinking", {"transcript": turn_text})
            if mqtt_client:
                await mqtt_client.publish(
                    f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                    "speaking",
                )

            async def _say(text: str) -> None:
                await asyncio.to_thread(get_tts().say, text, lang)

            reply = await engine.reply_streaming(turn_text, _say)
            if reply == _UNREACHABLE:
                if on_stt_event:
                    on_stt_event("llm_unreachable", {})
                await asyncio.to_thread(
                    get_tts().say, "agente remoto non raggiungibile", lang
                )
                break
            if on_stt_event:
                on_stt_event("llm_reply", {"transcript": turn_text, "reply": reply})
    finally:
        if mqtt_client:
            await mqtt_client.publish(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle"
            )


@registry.register("llm_learn")
async def handle_llm_learn(
    action: ActionEntry,
    listen_fn: Callable[..., Coroutine[Any, Any, str]] | None,
    mqtt_client: MQTTClient | None,
    actions_config=None,
    wake_word: str | None = None,
    **_,
) -> None:
    from alexa_custom.llm import LearnWizard
    from alexa_custom.tts import get_engine as get_tts

    if actions_config is None or actions_config.llm is None:
        logger.warning("llm_learn action: LLM not configured — skipping")
        return
    if listen_fn is None:
        logger.warning("llm_learn action: no listen_fn available — skipping")
        return
    if actions_config.actions is None or not actions_config.actions.learn_file:
        logger.warning("llm_learn action: no actions.learn_file configured — skipping")
        return

    cfg = actions_config.llm
    lang = "it-IT"
    if wake_word and actions_config.wake_words:
        for grp in actions_config.wake_words:
            if grp.word == wake_word:
                lang = grp.lang
                break

    async def say_fn(text: str) -> None:
        await asyncio.to_thread(get_tts().say, text, lang)

    wizard = LearnWizard(
        config=cfg,
        lang=lang,
        actions_file_path=actions_config.actions.learn_file,
        wake_word=wake_word,
    )
    await wizard.run(listen_fn, say_fn)


ITALIAN_CITIES: dict[str, tuple[float, float]] = {
    "roma": (41.8919, 12.5113),
    "milano": (45.4642, 9.1900),
    "napoli": (40.8518, 14.2681),
    "torino": (45.0703, 7.6869),
    "palermo": (38.1157, 13.3615),
    "genova": (44.4056, 8.9463),
    "bologna": (44.4949, 11.3426),
    "firenze": (43.7696, 11.2558),
    "bari": (41.1171, 16.8719),
    "venezia": (45.4408, 12.3155),
    "verona": (45.4384, 10.9916),
    "messina": (38.1938, 15.5540),
    "padova": (45.4064, 11.8760),
    "trieste": (45.6495, 13.7768),
    "brescia": (45.5416, 10.2118),
    "parma": (44.8015, 10.3279),
    "prato": (43.8777, 11.1022),
    "modena": (44.6471, 10.9252),
    "reggio calabria": (38.1144, 15.6500),
    "reggio emilia": (44.6982, 10.6312),
    "perugia": (43.1107, 12.3908),
    "ravenna": (44.4184, 12.2035),
    "livorno": (43.5485, 10.3106),
    "cagliari": (39.2238, 9.1217),
    "foggia": (41.4622, 15.5446),
    "rimini": (44.0594, 12.5684),
    "salerno": (40.6780, 14.7594),
    "ferrara": (44.8381, 11.6198),
    "sassari": (40.7259, 8.5556),
    "latina": (41.4676, 12.9036),
    "giugliano in campania": (40.9317, 14.1956),
    "monza": (45.5845, 9.2744),
    "siracusa": (37.0755, 15.2866),
    "pescara": (42.4618, 14.2185),
    "bergamo": (45.6983, 9.6773),
    "forli": (44.2227, 12.0409),
    "trento": (46.0679, 11.1211),
    "vicenza": (45.5480, 11.5494),
    "terni": (42.5638, 12.6414),
    "bolzano": (46.4908, 11.3398),
    "novara": (45.4468, 8.6214),
    "piacenza": (45.0526, 9.6930),
    "ancona": (43.6158, 13.5189),
    "andria": (41.2263, 16.2974),
    "arezzo": (43.4631, 11.8780),
    "udine": (46.0711, 13.2446),
    "cesena": (44.1396, 12.2431),
    "lecce": (40.3515, 18.1751),
}

WMO_INTERPRETATION: dict[int, str] = {
    0: "Cielo sereno",
    1: "Prevalentemente sereno",
    2: "Parzialmente nuvoloso",
    3: "Coperto",
    45: "Nebbia",
    48: "Nebbia brinante",
    51: "Pioggerella leggera",
    53: "Pioggerella moderata",
    55: "Pioggerella fitta",
    56: "Pioggerella gelida leggera",
    57: "Pioggerella gelida fitta",
    61: "Pioggia debole",
    63: "Pioggia moderata",
    65: "Pioggia forte",
    66: "Pioggia gelida debole",
    67: "Pioggia gelida forte",
    71: "Nevicata debole",
    73: "Nevicata moderata",
    75: "Nevicata forte",
    77: "Neve in grani",
    80: "Rovesci di pioggia deboli",
    81: "Rovesci di pioggia moderati",
    82: "Rovesci di pioggia violenti",
    85: "Rovesci di neve deboli",
    86: "Rovesci di neve forti",
    95: "Temporale",
    96: "Temporale con grandine debole",
    99: "Temporale con grandine forte",
}

WMO_INTERPRETATION_EN: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


@registry.register("meteo")
async def handle_meteo(
    action: ActionEntry,
    mqtt_client: MQTTClient | None,
    transcript: str | None = None,
    actions_config=None,
    wake_word: str | None = None,
    **_,
) -> None:
    latitude = action.params.get("latitude")
    longitude = action.params.get("longitude")
    city_name = action.params.get("city")
    days_param = action.params.get("days")

    lang = action.params.get("lang")
    if not lang:
        lang = "it-IT"
        if (
            wake_word
            and actions_config
            and hasattr(actions_config, "wake_words")
            and actions_config.wake_words
        ):
            for grp in actions_config.wake_words:
                if grp.word == wake_word:
                    lang = grp.lang
                    break

    is_it = lang.lower().startswith("it")

    # Resolve coordinates and city name
    if latitude is None or longitude is None:
        resolved_coords = None
        if transcript:
            norm_t = normalize_text(transcript)
            # Find largest matching city name to avoid sub-string collisions
            sorted_cities = sorted(ITALIAN_CITIES.keys(), key=len, reverse=True)
            for city in sorted_cities:
                pattern = r"\b" + re.escape(city) + r"\b"
                if re.search(pattern, norm_t):
                    city_name = city
                    resolved_coords = ITALIAN_CITIES[city]
                    break

        if resolved_coords is None and city_name:
            norm_param_city = normalize_text(city_name)
            if norm_param_city in ITALIAN_CITIES:
                resolved_coords = ITALIAN_CITIES[norm_param_city]

        if resolved_coords is not None:
            latitude, longitude = resolved_coords
        else:
            # Absolute fallback to Rome
            city_name = city_name or "Roma"
            latitude, longitude = ITALIAN_CITIES["roma"]
    else:
        city_name = city_name or "la tua posizione"

    # Resolve forecast day (0 = today, 1 = tomorrow)
    day_index = 1
    day_label = "domani" if is_it else "tomorrow"

    if transcript:
        norm_t = normalize_text(transcript)
        if "domani" in norm_t or "tomorrow" in norm_t:
            day_index = 1
            day_label = "domani" if is_it else "tomorrow"
        elif "oggi" in norm_t or "today" in norm_t:
            day_index = 0
            day_label = "oggi" if is_it else "today"
        elif days_param is not None:
            if str(days_param).lower() in ["oggi", "today", "0"]:
                day_index = 0
                day_label = "oggi" if is_it else "today"
            else:
                day_index = 1
                day_label = "domani" if is_it else "tomorrow"
    elif days_param is not None:
        if str(days_param).lower() in ["oggi", "today", "0"]:
            day_index = 0
            day_label = "oggi" if is_it else "today"
        else:
            day_index = 1
            day_label = "domani" if is_it else "tomorrow"

    display_city = city_name.title() if city_name else "Roma"

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
        "forecast_days": 2,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Open-Meteo API request failed: {e}")
        fail_msg = (
            "Spiacente, impossibile recuperare le informazioni meteo al momento."
            if is_it
            else "Sorry, I cannot retrieve weather information at the moment."
        )
        from alexa_custom.tts import get_engine

        if mqtt_client:
            await mqtt_client.publish(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                "speaking",
            )
        await asyncio.to_thread(get_engine().say, fail_msg, lang)
        if mqtt_client:
            await mqtt_client.publish(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                "idle",
            )
        return

    daily = data.get("daily", {})
    weather_codes = daily.get("weather_code", [])
    temp_maxs = daily.get("temperature_2m_max", [])
    temp_mins = daily.get("temperature_2m_min", [])

    if (
        len(weather_codes) > day_index
        and len(temp_maxs) > day_index
        and len(temp_mins) > day_index
    ):
        code = weather_codes[day_index]
        t_max = temp_maxs[day_index]
        t_min = temp_mins[day_index]

        t_max_int = int(round(t_max))
        t_min_int = int(round(t_min))

        if is_it:
            desc = WMO_INTERPRETATION.get(code, "tempo variabile")
            weather_msg = (
                f"A {display_city} {day_label} il tempo sarà: {desc.lower()}. "
                f"La temperatura minima sarà di {t_min_int} gradi, e la massima di {t_max_int} gradi."
            )
        else:
            desc = WMO_INTERPRETATION_EN.get(code, "variable weather")
            weather_msg = (
                f"In {display_city} {day_label} the weather will be: {desc.lower()}. "
                f"The minimum temperature will be {t_min_int} degrees, and the maximum will be {t_max_int} degrees."
            )

        logger.info(f"[meteo action] Saying: {weather_msg}")
        from alexa_custom.tts import get_engine

        if mqtt_client:
            await mqtt_client.publish(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                "speaking",
            )
        await asyncio.to_thread(get_engine().say, weather_msg, lang)
        if mqtt_client:
            await mqtt_client.publish(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                "idle",
            )
    else:
        logger.warning("Open-Meteo API returned incomplete daily data")


@registry.register("stop_listening")
async def handle_stop_listening(
    action: ActionEntry,
    on_stt_event: Callable[[str, dict], None] | None = None,
    actions_config=None,
    **_,
):
    from alexa_custom.stt import set_stt_sleeping

    logger.info("Action: stop_listening — putting assistant to sleep")
    set_stt_sleeping(True)
    if on_stt_event:
        wake_up_phrases = []
        if actions_config:
            for t in getattr(actions_config, "direct_triggers", []):
                if any(a.type == "start_listening" for a in t.actions):
                    wake_up_phrases.append(t.phrase)
            for t in getattr(actions_config, "triggers", []):
                if any(a.type == "start_listening" for a in t.actions):
                    wake_up_phrases.append(t.phrase)
            for g in getattr(actions_config, "wake_words", []):
                for t in g.triggers:
                    if any(a.type == "start_listening" for a in t.actions):
                        wake_up_phrases.append(t.phrase)
        phrases_str = ", ".join(sorted(list(set(wake_up_phrases))))
        on_stt_event("sleeping", {"wake_up_phrase": phrases_str})


@registry.register("start_listening")
async def handle_start_listening(
    action: ActionEntry,
    on_stt_event: Callable[[str, dict], None] | None = None,
    actions_config=None,
    **_,
):
    from alexa_custom.stt import set_stt_sleeping

    logger.info("Action: start_listening — waking up assistant")
    set_stt_sleeping(False)
    if on_stt_event:
        wake_words = (
            [g.word for g in actions_config.wake_words] if actions_config else []
        )
        on_stt_event("listening", {"wake_words": wake_words})


def _read_system_vitals() -> dict:
    import glob

    vitals: dict = {}

    # CPU temperature — max across all thermal zones
    try:
        temps = []
        for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
            try:
                with open(path) as f:
                    temps.append(int(f.read().strip()))
            except (OSError, ValueError):
                pass
        if temps:
            vitals["temp_c"] = max(temps) // 1000
    except Exception:
        pass

    # Load average — 1-minute value
    try:
        with open("/proc/loadavg") as f:
            vitals["load"] = float(f.read().split()[0])
    except Exception:
        pass

    # Free memory — MemAvailable in kB
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    vitals["free_kb"] = int(line.split()[1])
                    break
    except Exception:
        pass

    # Uptime in seconds
    try:
        with open("/proc/uptime") as f:
            vitals["uptime_s"] = float(f.read().split()[0])
    except Exception:
        pass

    return vitals


def _format_system_info_italian(vitals: dict) -> str:
    parts = []

    if "temp_c" in vitals:
        parts.append(f"temperatura {vitals['temp_c']} gradi")

    if "load" in vitals:
        parts.append(f"carico {vitals['load']:.1f}")

    if "free_kb" in vitals:
        free_gb = vitals["free_kb"] / (1024 * 1024)
        if free_gb >= 1.0:
            parts.append(f"memoria libera {free_gb:.0f} gigabyte")
        else:
            free_mb = vitals["free_kb"] // 1024
            parts.append(f"memoria libera {free_mb} megabyte")

    if "uptime_s" in vitals:
        secs = int(vitals["uptime_s"])
        days, secs = divmod(secs, 86400)
        hours, secs = divmod(secs, 3600)
        minutes = secs // 60
        units = []
        if days:
            units.append(
                f"{'un' if days == 1 else str(days)} {'giorno' if days == 1 else 'giorni'}"
            )
        if hours and len(units) < 2:
            units.append(
                f"{'un' if hours == 1 else str(hours)} {'ora' if hours == 1 else 'ore'}"
            )
        if minutes and len(units) < 2:
            units.append(f"{minutes} {'minuto' if minutes == 1 else 'minuti'}")
        if units:
            parts.append("attivo da " + " e ".join(units))

    if not parts:
        return "Dati di sistema non disponibili."
    return "Il sistema: " + ", ".join(parts) + "."


@registry.register("system_info")
async def handle_system_info(
    action: ActionEntry, mqtt_client: "MQTTClient | None" = None, **_
):
    from alexa_custom.tts import get_engine

    vitals = await asyncio.to_thread(_read_system_vitals)
    text = _format_system_info_italian(vitals)
    logger.info("system_info: %s", text)
    if mqtt_client:
        await mqtt_client.publish(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "speaking"
        )
    await asyncio.to_thread(get_engine().say, text, "it-IT")
    if mqtt_client:
        await mqtt_client.publish(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle"
        )


@registry.register("restart")
async def handle_restart(action: ActionEntry, **_):
    logger.info("Action: restart — restarting application...")
    await asyncio.sleep(0.5)
    import os
    import sys

    os.execv(sys.executable, [sys.executable] + sys.argv)


def _calibration_winner(scores: dict[float, float]) -> float:
    """Return the gain with the highest score, preferring the lower gain on ties."""
    return min(scores, key=lambda g: (-scores[g], g))


def _calibration_round2_gains(
    winner: float, gain_low: float, gain_high: float
) -> list[float]:
    """Return two probe gains zooming into the neighbourhood around the Round 1 winner."""
    half_step = (gain_high - gain_low) / 6.0
    return [max(0.0, winner - half_step), winner + half_step]


@registry.register("calibrate_input_gain")
async def handle_calibrate_input_gain(
    action: ActionEntry,
    listen_fn: Callable[[float], Awaitable[str]] | None = None,
    **_,
):
    """Adaptive 5-probe mic gain calibration.

    Example YAML:
        - type: calibrate_input_gain
          params:
            sentence: "uno due tre quattro cinque"
            gain_low: 0.4
            gain_mid: 0.7
            gain_high: 1.2
            listen_timeout: 6.0
            settle_ms: 500
    """
    from alexa_custom.audio_hw import (
        save_input_gain_config,
        set_input_gain,
    )
    from alexa_custom.tts import get_engine

    if listen_fn is None:
        logger.warning("calibrate_input_gain: no listen_fn available — skipping")
        return

    sentence = action.params.get("sentence", "uno due tre quattro cinque")
    gain_low = float(action.params.get("gain_low", 0.4))
    gain_mid = float(action.params.get("gain_mid", 0.7))
    gain_high = float(action.params.get("gain_high", 1.2))
    listen_timeout = float(action.params.get("listen_timeout", 6.0))
    settle_ms = float(action.params.get("settle_ms", 500))
    settle_s = settle_ms / 1000.0

    scores: dict[float, float] = {}
    probe_num = 0

    logger.info("calibrate_input_gain: starting calibration (sentence=%r)", sentence)
    await asyncio.to_thread(
        get_engine().say,
        "Iniziamo la calibrazione. Ripeti ogni frase che sento.",
        "it-IT",
    )

    async def _probe(gain: float) -> None:
        nonlocal probe_num
        probe_num += 1
        label = f"prova {probe_num} di 5: {sentence}"
        logger.info("calibrate_input_gain: probe %d gain=%.2f", probe_num, gain)
        await asyncio.to_thread(set_input_gain, None, None, gain)
        await asyncio.sleep(settle_s)
        await asyncio.to_thread(get_engine().say, label, "it-IT")
        transcript = await listen_fn(listen_timeout)
        score = get_similarity_score(
            normalize_text(transcript or ""),
            normalize_text(sentence),
            "levenshtein",
        )
        logger.info(
            "calibrate_input_gain: gain=%.2f score=%.1f transcript=%r",
            gain,
            score,
            transcript,
        )
        scores[gain] = score

    # Round 1 — bracket
    for g in [gain_low, gain_mid, gain_high]:
        await _probe(g)

    r1_winner = _calibration_winner(scores)

    # Round 2 — zoom
    for g in _calibration_round2_gains(r1_winner, gain_low, gain_high):
        await _probe(g)

    best_gain = _calibration_winner(scores)
    logger.info(
        "calibrate_input_gain: best gain=%.2f (score=%.1f), all scores=%s",
        best_gain,
        scores[best_gain],
        {f"{g:.2f}": f"{s:.1f}" for g, s in sorted(scores.items())},
    )

    await asyncio.to_thread(set_input_gain, None, None, best_gain)
    save_input_gain_config(best_gain)

    pct = int(round(best_gain * 100))
    await asyncio.to_thread(
        get_engine().say,
        f"Calibrazione completata. Guadagno impostato a {pct} percento.",
        "it-IT",
    )


@registry.register("record_and_playback")
@registry.register("register_and_playback")
async def handle_record_and_playback(
    action: ActionEntry,
    actions_config=None,
    **_,
):
    """Record a sample of audio (default 7 seconds) and play it back.

    Example YAML:
        - type: record_and_playback
          params:
            duration: 7.0
    """
    from alexa_custom.stt_gating import resolve_capture_source
    from alexa_custom.audio_ops import record_wav_file, play_wav_file, play_tone
    import tempfile

    duration = float(action.params.get("duration", 7.0))

    input_spec = None
    if actions_config and hasattr(actions_config, "audio"):
        input_spec = actions_config.audio.input_device

    source, channels = resolve_capture_source(input_spec)
    logger.info(
        "record_and_playback: recording %s seconds of audio using source=%s (%d ch)",
        duration,
        source or "default",
        channels,
    )

    try:
        await asyncio.to_thread(play_tone, "info")
    except Exception as e:
        logger.warning("record_and_playback: failed to play start tone: %s", e)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_wav = f.name

    try:
        await asyncio.to_thread(record_wav_file, tmp_wav, duration, source, channels)
        logger.info("record_and_playback: playing back recorded sample")
        await asyncio.to_thread(play_wav_file, tmp_wav)
    finally:
        try:
            os.unlink(tmp_wav)
        except OSError:
            pass


async def _run_action(
    action: ActionEntry,
    ctx: ActionContext,
    *,
    wake_word: str | None = None,
    transcript: str | None = None,
) -> None:
    await registry.execute(
        action.type,
        action=action,
        ctx=ctx,
        telegram_client=ctx.telegram_client,
        livekit_connect_fn=ctx.livekit_connect_fn,
        livekit_connected=ctx.livekit_connected,
        listen_fn=ctx.listen_fn,
        mqtt_client=ctx.mqtt_client,
        on_stt_event=ctx.on_stt_event,
        actions_config=ctx.actions_config,
        wake_word=wake_word,
        transcript=transcript,
    )
