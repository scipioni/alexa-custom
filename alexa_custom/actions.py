from __future__ import annotations

import difflib
import logging
import os
from typing import Awaitable, Callable

import httpx

from alexa_custom.config import ActionEntry, Trigger

logger = logging.getLogger(__name__)


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
    t_lower = transcript.lower().strip()
    for trigger in triggers:
        score = difflib.SequenceMatcher(None, t_lower, trigger.phrase.lower()).ratio()
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
) -> None:
    for action in trigger.actions:
        await _run_action(
            action, telegram_client, livekit_connect_fn, livekit_connected
        )


async def _run_action(
    action: ActionEntry,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected: bool,
) -> None:
    if action.type == "log":
        message = action.params.get("message", "(no message)")
        logger.info(f"[log action] {message}")

    elif action.type == "telegram":
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

    elif action.type == "livekit_join":
        if livekit_connected:
            logger.debug("livekit_join action: already connected, skipping")
            return
        if livekit_connect_fn is None:
            logger.warning("livekit_join action: no connect function available")
            return
        await livekit_connect_fn()

    elif action.type == "say":
        from alexa_custom.tts import get_engine

        text = action.params.get("text", "")
        lang = action.params.get("lang", "it-IT")
        if text:
            # We run in a thread because TTS generation/playback is blocking
            import asyncio

            await asyncio.to_thread(get_engine().say, text, lang)

    else:
        logger.warning(f"Unknown action type '{action.type}' — skipping")
