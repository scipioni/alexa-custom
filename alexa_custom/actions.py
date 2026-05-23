from __future__ import annotations

import asyncio
import difflib
import logging
import os
import unicodedata
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


def match_trigger(
    transcript: str,
    triggers: list[Trigger],
    threshold: float = 0.70,
) -> Trigger | None:
    best: Trigger | None = None
    best_score = 0.0
    t_norm = normalize_text(transcript)
    for trigger in triggers:
        p_norm = normalize_text(trigger.phrase)
        score = difflib.SequenceMatcher(None, t_norm, p_norm).ratio()
        if score > best_score:
            best_score = score
            best = trigger
    if best is not None and best_score >= threshold:
        logger.info(f"Matched trigger '{best.phrase}' (score={best_score:.2f})")
        return best
    logger.debug(f"No trigger matched '{transcript}' (best score={best_score:.2f})")
    return None


async def dispatch(
    trigger: Trigger,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected: bool = False,
    listen_fn: Callable[[float], Awaitable[str]] | None = None,
    mqtt_client: MQTTClient | None = None,
    on_stt_event: Callable[[str, dict], None] | None = None,
) -> None:
    for action in trigger.actions:
        await _run_action(
            action,
            telegram_client,
            livekit_connect_fn,
            livekit_connected,
            listen_fn,
            mqtt_client,
            on_stt_event,
        )


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


@registry.register("say")
async def handle_say(action: ActionEntry, mqtt_client: MQTTClient | None, **_):
    from alexa_custom.tts import get_engine

    text = action.params.get("text", "")
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
        reply_trigger = match_trigger(transcript, action.on_reply)
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
            )

    if mqtt_client:
        await mqtt_client.publish(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle"
        )


@registry.register("tone")
async def handle_tone(action: ActionEntry, **_):
    from alexa_custom.audio import play_tone

    name = action.params.get("name", "info")
    await asyncio.to_thread(play_tone, name)


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


async def _run_action(
    action: ActionEntry,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected: bool,
    listen_fn: Callable[[float], Awaitable[str]] | None = None,
    mqtt_client: MQTTClient | None = None,
    on_stt_event: Callable[[str, dict], None] | None = None,
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
    )
