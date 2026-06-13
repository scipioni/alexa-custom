from __future__ import annotations

import asyncio
import logging
import os
import re
import unicodedata
from datetime import datetime
from typing import Awaitable, Callable, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from alexa_custom.mqtt import MQTTClient

from alexa_custom.config import ActionEntry, Trigger

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """Lowercase and remove diacritics (e.g., 'sì' -> 'si')."""
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", text.lower())
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


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Levenshtein distance between two strings using dynamic programming."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (0 if c1 == c2 else 1)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def get_similarity_score(a: str, b: str, algorithm: str) -> float:
    """Calculate a similarity score (0.0 - 100.0) between two strings based on algorithm."""
    if not a or not b:
        return 0.0

    # 1. Try using rapidfuzz
    try:
        from rapidfuzz import fuzz as _fuzz
        from rapidfuzz.distance import Levenshtein as _lev

        if algorithm == "levenshtein":
            max_len = max(len(a), len(b))
            if max_len == 0:
                return 100.0
            dist = _lev.distance(a, b)
            return (1.0 - (dist / max_len)) * 100.0
        elif algorithm == "ratio":
            return _fuzz.ratio(a, b)
        else:  # "token_set_ratio"
            return _fuzz.token_set_ratio(a, b)

    # 2. Fall back if rapidfuzz is not installed
    except ImportError:
        if algorithm == "levenshtein":
            max_len = max(len(a), len(b))
            if max_len == 0:
                return 100.0
            dist = levenshtein_distance(a, b)
            return (1.0 - (dist / max_len)) * 100.0
        else:  # "ratio" or "token_set_ratio" fallback
            import difflib

            return difflib.SequenceMatcher(None, a, b).ratio() * 100.0


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


def match_trigger(
    transcript: str,
    triggers: list[Trigger],
    threshold: float = _TRIGGER_THRESHOLD,
    algorithm: str = "token_set_ratio",
) -> Trigger | None:
    # Pattern match is definitive: first trigger whose patterns match wins.
    for trigger in triggers:
        if trigger.patterns and _trigger_matches_patterns(
            trigger, transcript, algorithm, threshold
        ):
            logger.info(f"Matched trigger '{trigger.phrase}' (glob pattern)")
            return trigger

    # Fuzzy fallback: best phonetic similarity score above threshold.
    best: Trigger | None = None
    best_score = 0.0
    t_phon = italian_phonetic(transcript)
    for trigger in triggers:
        phrases = [trigger.phrase] + trigger.aliases
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
        logger.info(f"Matched trigger '{best.phrase}' (score={best_score:.0f})")
        return best
    logger.debug(f"No trigger matched '{transcript}' (best score={best_score:.0f})")
    return None


_dispatch_depth = 0
_MAX_DISPATCH_DEPTH = 10


async def dispatch(
    trigger: Trigger,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected: bool = False,
    listen_fn: Callable[[float], Awaitable[str]] | None = None,
    mqtt_client: MQTTClient | None = None,
    on_stt_event: Callable[[str, dict], None] | None = None,
    actions_config=None,
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
            await _run_action(
                action,
                telegram_client,
                livekit_connect_fn,
                livekit_connected,
                listen_fn,
                mqtt_client,
                on_stt_event,
                actions_config=actions_config,
                wake_word=wake_word,
                transcript=transcript,
            )
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


_WEEKDAYS_IT = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
_MONTHS_IT = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
              'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']


def _date_ita() -> str:
    now = datetime.now()
    return (f"Oggi è {_WEEKDAYS_IT[now.weekday()]} {now.day} "
            f"{_MONTHS_IT[now.month - 1]} {now.year}")


_CMD_RE = re.compile(r"\$\(([^)]+)\)")


async def _render_text(text: str) -> str:
    """Expand $date_ita and $(shell command) placeholders in text."""

    text = text.replace("$date_ita", _date_ita())

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
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected: bool,
    listen_fn: Callable[[float], Awaitable[str]] | None,
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

    # Use constrained grammar if triggers are defined to improve accuracy (e.g., 'si' vs 'se')
    phrases = [t.phrase for t in action.on_reply]

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

        reply_trigger = match_trigger(
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
                    {"transcript": transcript, "trigger": reply_trigger.phrase},
                )
            await dispatch(
                reply_trigger,
                telegram_client,
                livekit_connect_fn,
                livekit_connected,
                listen_fn,
                mqtt_client,
                on_stt_event,
                actions_config=actions_config,
                wake_word=wake_word,
                transcript=transcript,
            )
        elif action.on_else:
            logger.info(f"No reply trigger matched '{transcript}', running on_else")
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": transcript})
            for else_action in action.on_else:
                await _run_action(
                    else_action,
                    telegram_client,
                    livekit_connect_fn,
                    livekit_connected,
                    listen_fn,
                    mqtt_client,
                    on_stt_event,
                    actions_config=actions_config,
                    wake_word=wake_word,
                )
        else:
            logger.info(f"No reply trigger matched '{transcript}' and no on_else")
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": transcript})
            from alexa_custom.audio import play_timeout_beep

            await asyncio.to_thread(play_timeout_beep)
    elif action.on_else:
        logger.info("No transcript received (timeout), running on_else")
        for else_action in action.on_else:
            await _run_action(
                else_action,
                telegram_client,
                livekit_connect_fn,
                livekit_connected,
                listen_fn,
                mqtt_client,
                on_stt_event,
                actions_config=actions_config,
                wake_word=wake_word,
            )
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
    listen_fn: Callable[[float], Awaitable[str]] | None,
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
    listen_fn: Callable[[float], Awaitable[str]] | None,
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


async def _run_action(
    action: ActionEntry,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected: bool,
    listen_fn: Callable[[float], Awaitable[str]] | None = None,
    mqtt_client: MQTTClient | None = None,
    on_stt_event: Callable[[str, dict], None] | None = None,
    actions_config=None,
    wake_word: str | None = None,
    transcript: str | None = None,
) -> None:
    await registry.execute(
        action.type,
        action=action,
        telegram_client=telegram_client,
        livekit_connect_fn=livekit_connect_fn,
        livekit_connected=livekit_connected,
        listen_fn=listen_fn,
        mqtt_client=mqtt_client,
        on_stt_event=on_stt_event,
        actions_config=actions_config,
        wake_word=wake_word,
        transcript=transcript,
    )
