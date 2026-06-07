from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from alexa_custom.config import ActionEntry, ActionsData, LLMConfig, Trigger

logger = logging.getLogger(__name__)

_UNREACHABLE = "__UNREACHABLE__"

_WIZARD_ALLOWED_TYPES = {
    "say",
    "tone",
    "shell",
    "mqtt_publish",
    "telegram",
    "livekit_join",
}

_TONE_NAMES = {"startup", "success", "error", "info", "warning", "wake"}

# Required params per action type (empty = no required params beyond type)
_ACTION_PARAMS: dict[str, list[str]] = {
    "say": ["text"],
    "tone": ["name"],
    "shell": ["command"],
    "mqtt_publish": ["topic", "payload"],
    "telegram": ["text"],
    "livekit_join": [],
}

_ACTION_LABELS: dict[str, str] = {
    "say": "dire qualcosa",
    "tone": "riprodurre un suono",
    "shell": "eseguire un comando",
    "mqtt_publish": "pubblicare su MQTT",
    "telegram": "inviare un messaggio Telegram",
    "livekit_join": "connettersi a LiveKit",
}

_PARAM_QUESTIONS: dict[str, dict[str, str]] = {
    "say": {"text": "Cosa devo dire?"},
    "tone": {"name": f"Quale suono? Scegli tra: {', '.join(sorted(_TONE_NAMES))}."},
    "shell": {"command": "Quale comando devo eseguire?"},
    "mqtt_publish": {
        "topic": "Su quale topic MQTT devo pubblicare?",
        "payload": "Quale payload?",
    },
    "telegram": {"text": "Quale testo devo inviare?"},
    "livekit_join": {},
}


class OllamaUnreachable(Exception):
    pass


_CONNECT_TIMEOUT = 5.0  # seconds to establish TCP connection

# Sentence boundary characters used by the streaming sentence splitter.
_SENTENCE_END = frozenset(".!?")


def _split_sentences(buf: str) -> tuple[list[str], str]:
    """Return (complete_sentences, remainder) from buf.

    Avoids splitting on '.' inside decimal numbers (e.g. "10.5 gradi") or when
    the next non-whitespace character is lowercase (mid-sentence continuation).
    """
    sentences: list[str] = []
    start = 0
    for i, ch in enumerate(buf):
        if ch not in _SENTENCE_END:
            continue
        if ch == ".":
            prev = buf[i - 1] if i > 0 else ""
            end = i + 1
            while end < len(buf) and buf[end] in " \t":
                end += 1
            nxt = buf[end] if end < len(buf) else ""
            # decimal numbers: digit.digit; mid-sentence: next char is lowercase
            if prev.isdigit() or (nxt and not nxt.isupper()):
                continue
        else:
            end = i + 1
            while end < len(buf) and buf[end] in " \t":
                end += 1
        sentence = buf[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = end
    return sentences, buf[start:]


class OllamaClient:
    def __init__(self, host: str, timeout: float = 60.0) -> None:
        self._host = host.rstrip("/")
        self._timeout = timeout
        self._http_timeout = httpx.Timeout(
            connect=_CONNECT_TIMEOUT, read=self._timeout, write=10.0, pool=5.0
        )

    async def chat(self, messages: list[dict[str, str]], model: str) -> str:
        """Collect a full reply (non-streaming). Used by LearnWizard."""
        tokens: list[str] = []
        async for token in self.chat_stream(messages, model):
            tokens.append(token)
        return "".join(tokens)

    async def warmup(self, model: str) -> None:
        """Pre-load the model by sending an empty generation request."""
        url = f"{self._host}/api/generate"
        payload = {"model": model, "prompt": "", "stream": False, "keep_alive": -1}
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                await client.post(url, json=payload)
            logger.debug("Ollama warmup complete for model %s", model)
        except Exception as e:
            logger.debug("Ollama warmup skipped: %s", e)

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
    ):
        """Yield text token strings as they arrive from the streaming API."""
        url = f"{self._host}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": -1,
        }
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        raise OllamaUnreachable(
                            f"Ollama returned HTTP {resp.status_code}: {body[:200]}"
                        )
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = __import__("json").loads(line)
                        except ValueError:
                            continue
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
        except httpx.TimeoutException as e:
            raise OllamaUnreachable(
                f"Ollama timeout after {self._timeout}s: {e}"
            ) from e
        except httpx.HTTPError as e:
            raise OllamaUnreachable(f"Ollama HTTP error: {e}") from e


class OpenAIClient:
    """OpenAI-compatible chat client (any /v1/chat/completions endpoint)."""

    def __init__(self, host: str, api_key: str = "", timeout: float = 60.0) -> None:
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._http_timeout = httpx.Timeout(
            connect=_CONNECT_TIMEOUT, read=timeout, write=10.0, pool=5.0
        )

    async def chat(self, messages: list[dict[str, str]], model: str) -> str:
        tokens: list[str] = []
        async for token in self.chat_stream(messages, model):
            tokens.append(token)
        return "".join(tokens)

    async def warmup(self, model: str) -> None:
        pass

    async def chat_stream(self, messages: list[dict[str, str]], model: str):
        url = f"{self._host}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        payload = {"model": model, "messages": messages, "stream": True}
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                async with client.stream(
                    "POST", url, json=payload, headers=headers
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        raise OllamaUnreachable(
                            f"OpenAI API returned HTTP {resp.status_code}: {body[:200]}"
                        )
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        try:
                            chunk = __import__("json").loads(data)
                        except ValueError:
                            continue
                        token = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if token:
                            yield token
        except httpx.TimeoutException as e:
            raise OllamaUnreachable(
                f"OpenAI API timeout after {self._timeout}s: {e}"
            ) from e
        except httpx.HTTPError as e:
            raise OllamaUnreachable(f"OpenAI API HTTP error: {e}") from e


class ConversationEngine:
    def __init__(self, config: LLMConfig, lang: str = "it-IT") -> None:
        self._config = config
        self._lang = lang
        if config.backend == "openai":
            self._client: OllamaClient | OpenAIClient = OpenAIClient(
                config.host, config.api_key, config.request_timeout
            )
        else:
            self._client = OllamaClient(config.host, config.request_timeout)
        self._history: list[dict[str, str]] = []
        self._last_ts: float = 0.0

    def _system_prompt(self) -> str:
        if self._config.system_prompt:
            return self._config.system_prompt
        lang_label = {
            "it-IT": "italiano",
            "en-US": "English",
            "en-GB": "English",
            "fr-FR": "français",
            "de-DE": "Deutsch",
            "es-ES": "español",
        }.get(self._lang, self._lang)
        return (
            f"Sei un assistente vocale. Rispondi in modo conciso, in {lang_label}. "
            "Non usare elenchi, markdown, simboli speciali o formattazione. "
            "Le tue risposte saranno lette da un sintetizzatore vocale."
        )

    def _prepare_messages(self, user_text: str) -> list[dict[str, str]]:
        now = time.monotonic()
        if self._history and (now - self._last_ts) > self._config.context_window_secs:
            logger.debug("ConversationEngine: context window expired, clearing history")
            self._history.clear()
        self._last_ts = now
        self._history.append({"role": "user", "content": user_text})
        return [{"role": "system", "content": self._system_prompt()}] + self._history

    def _commit(self, full_text: str) -> None:
        self._history.append({"role": "assistant", "content": full_text})
        max_msgs = self._config.context_turns * 2
        if len(self._history) > max_msgs:
            self._history = self._history[-max_msgs:]

    async def reply_streaming(
        self,
        user_text: str,
        say_fn: Callable[[str], Awaitable[None]],
    ) -> str:
        """Stream tokens from Ollama and speak each sentence as it completes.

        Returns the full reply text, or _UNREACHABLE on connection failure.
        """
        messages = self._prepare_messages(user_text)
        buf = ""
        full_text = ""
        try:
            async with asyncio.timeout(self._config.request_timeout):
                async for token in self._client.chat_stream(
                    messages, self._config.model
                ):
                    buf += token
                    sentences, buf = _split_sentences(buf)
                    for sentence in sentences:
                        full_text += sentence + " "
                        await say_fn(sentence)
            # Speak any remaining fragment (no trailing punctuation)
            remainder = buf.strip()
            if remainder:
                full_text += remainder
                await say_fn(remainder)
        except (OllamaUnreachable, TimeoutError) as e:
            logger.warning("Ollama streaming error or timeout: %s", e)
            if self._history:
                self._history.pop()
            return _UNREACHABLE

        self._commit(full_text.strip())
        return full_text.strip()

    async def warmup(self) -> None:
        await self._client.warmup(self._config.model)

    def reset(self) -> None:
        self._history.clear()
        self._last_ts = 0.0


# Module-level engine cache. Key includes system_prompt and request_timeout so a
# config hot-reload with changed values produces a fresh engine.
_engines: dict[tuple, ConversationEngine] = {}


def get_engine(config: LLMConfig, lang: str = "it-IT") -> ConversationEngine:
    key = (
        config.host,
        config.model,
        lang,
        config.system_prompt or "",
        config.request_timeout,
    )
    if key not in _engines:
        engine = ConversationEngine(config, lang)
        _engines[key] = engine
        # Fire-and-forget warmup: pre-loads the model so the first real
        # request doesn't pay the cold-start penalty.
        import asyncio as _aio

        try:
            loop = _aio.get_running_loop()
            loop.create_task(engine.warmup())
        except RuntimeError:
            pass  # no running loop (e.g. tests); warmup skipped
    return _engines[key]


class ActionsFileStore:
    _LEARNED_SEPARATOR = "# --- learned commands ---"

    @staticmethod
    def load(path: str | Path) -> ActionsData:
        from ruamel.yaml import YAML

        p = Path(path)
        yaml = YAML()
        if not p.exists():
            return ActionsData()
        with p.open() as f:
            raw = yaml.load(f) or {}
        if not isinstance(raw, dict):
            return ActionsData()

        from alexa_custom.config import (
            _parse_actions_file,
        )  # avoid circular at module level

        return _parse_actions_file(p)

    @staticmethod
    def save(path: str | Path, raw_content: str) -> None:
        """Write content atomically via temp-file rename."""
        p = Path(path)
        tmp = p.with_suffix(".yaml.tmp")
        tmp.write_text(raw_content, encoding="utf-8")
        tmp.rename(p)

    @staticmethod
    def append_trigger(
        path: str | Path,
        trigger: Trigger,
        wake_word: str | None = None,
    ) -> None:
        from ruamel.yaml import YAML
        from ruamel.yaml.comments import CommentedMap, CommentedSeq

        p = Path(path)
        yaml = YAML()
        yaml.default_flow_style = False
        yaml.preserve_quotes = True

        # Load existing content or start fresh
        file_exists = p.exists()
        if file_exists:
            with p.open() as f:
                doc = yaml.load(f)
        else:
            doc = None
            p.parent.mkdir(parents=True, exist_ok=True)

        if doc is None:
            doc = CommentedMap()

        def _action_to_dict(ae: ActionEntry) -> CommentedMap:
            d = CommentedMap()
            d["type"] = ae.type
            for k, v in ae.params.items():
                d[k] = v
            return d

        def _trigger_to_dict(t: Trigger) -> CommentedMap:
            d = CommentedMap()
            d["phrase"] = t.phrase
            actions_seq = CommentedSeq()
            for ae in t.actions:
                actions_seq.append(_action_to_dict(ae))
            d["actions"] = actions_seq
            return d

        trigger_dict = _trigger_to_dict(trigger)

        if wake_word:
            if "wake_triggers" not in doc:
                doc["wake_triggers"] = CommentedMap()
            wt = doc["wake_triggers"]
            if wake_word not in wt:
                wt[wake_word] = CommentedSeq()
            entries = wt[wake_word]
            entries.append(trigger_dict)
        else:
            if "triggers" not in doc:
                doc["triggers"] = CommentedSeq()
            entries = doc["triggers"]
            entries.append(trigger_dict)

        import io

        buf = io.StringIO()
        yaml.dump(doc, buf)
        content = buf.getvalue()

        if not file_exists:
            content = (
                "# conf/actions/learned.yaml — auto-created by the llm_learn action\n"
                "# Add or edit triggers here; loaded alphabetically after system.yaml.\n"
                "\n"
            ) + content

        sep = ActionsFileStore._LEARNED_SEPARATOR
        if sep not in content:
            # Insert separator comment before the last appended phrase
            marker = f"- phrase: {trigger.phrase}"
            idx = content.rfind(marker)
            if idx != -1:
                content = content[:idx] + f"{sep}\n" + content[idx:]

        ActionsFileStore.save(p, content)


class LearnWizard:
    def __init__(
        self,
        config: LLMConfig,
        lang: str,
        actions_file_path: str | Path,
        wake_word: str | None = None,
    ) -> None:
        self._config = config
        self._lang = lang
        self._actions_file = Path(actions_file_path)
        self._wake_word = wake_word
        self._client = OllamaClient(config.host, config.request_timeout)

    async def run(
        self,
        listen_fn: Callable[[float], Awaitable[str]],
        say_fn: Callable[[str], Awaitable[None]],
    ) -> Trigger | None:
        # Step 1: elicit trigger phrase
        await say_fn("Che frase vuoi usare per attivare questo comando?")
        phrase = (await listen_fn(10.0)).strip().lower()
        if not phrase:
            await say_fn("Nessuna frase ricevuta. Operazione annullata.")
            return None

        # Step 2: elicit action intent
        await say_fn("Cosa deve fare? Puoi dirmi una o più cose da fare in sequenza.")
        intent = (await listen_fn(15.0)).strip()
        if not intent:
            await say_fn("Nessuna azione specificata. Operazione annullata.")
            return None

        action_types = await self._extract_action_types(intent)
        if not action_types:
            await say_fn("Non ho capito. Puoi ripetere cosa vuoi che faccia?")
            intent = (await listen_fn(15.0)).strip()
            if intent:
                action_types = await self._extract_action_types(intent)
        if not action_types:
            await say_fn("Non ho capito le azioni da eseguire. Operazione annullata.")
            return None

        # Step 3: elicit params for each action
        action_entries: list[ActionEntry] = []
        for atype in action_types:
            if atype not in _WIZARD_ALLOWED_TYPES:
                await say_fn(
                    f"Il tipo di azione {atype} deve essere configurato manualmente. Lo salto."
                )
                continue
            params = await self._elicit_params(atype, listen_fn, say_fn)
            if params is None:
                await say_fn("Operazione annullata.")
                return None
            action_entries.append(ActionEntry(type=atype, params=params))

        if not action_entries:
            await say_fn("Nessuna azione valida. Operazione annullata.")
            return None

        # Step 4: confirmation
        summary = self._build_summary(phrase, action_entries)
        await say_fn(f"{summary}. Confermi?")
        confirm = normalize_confirm(await listen_fn(8.0))
        if confirm != "yes":
            await say_fn("Operazione annullata.")
            return None

        trigger = Trigger(phrase=phrase, actions=action_entries)
        ActionsFileStore.append_trigger(self._actions_file, trigger, self._wake_word)
        await say_fn("Comando salvato.")
        return trigger

    async def _extract_action_types(self, intent: str) -> list[str]:
        allowed_list = ", ".join(sorted(_WIZARD_ALLOWED_TYPES))
        system = (
            f"You are a command parser. The user describes what a voice assistant should do. "
            f"Return ONLY a comma-separated list of action type names from this set: {allowed_list}. "
            "No explanations, no other text. Example: 'say,mqtt_publish'"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": intent},
        ]
        try:
            raw = await self._client.chat(messages, self._config.model)
        except OllamaUnreachable:
            return []
        types = [t.strip().lower() for t in raw.split(",") if t.strip()]
        return [t for t in types if t in _WIZARD_ALLOWED_TYPES]

    async def _elicit_params(
        self,
        atype: str,
        listen_fn: Callable[[float], Awaitable[str]],
        say_fn: Callable[[str], Awaitable[None]],
    ) -> dict[str, Any] | None:
        questions = _PARAM_QUESTIONS.get(atype, {})
        params: dict[str, Any] = {}
        for param, question in questions.items():
            await say_fn(question)
            answer = (await listen_fn(10.0)).strip()
            if not answer:
                return None
            params[param] = answer
        return params

    def _build_summary(self, phrase: str, actions: list[ActionEntry]) -> str:
        parts = [f"Quando dici '{phrase}'"]
        for ae in actions:
            label = _ACTION_LABELS.get(ae.type, ae.type)
            if ae.type == "say":
                parts.append(f"dico '{ae.params.get('text', '')}'")
            elif ae.type == "mqtt_publish":
                parts.append(
                    f"pubblico '{ae.params.get('payload', '')}' su '{ae.params.get('topic', '')}'"
                )
            elif ae.type == "telegram":
                parts.append(f"invio '{ae.params.get('text', '')}' su Telegram")
            elif ae.type == "shell":
                parts.append(f"eseguo il comando '{ae.params.get('command', '')}'")
            elif ae.type == "tone":
                parts.append(f"riproduco il suono '{ae.params.get('name', '')}'")
            elif ae.type == "livekit_join":
                parts.append("mi connetto a LiveKit")
            else:
                parts.append(label)
        return ": ".join(parts[:1]) + " " + ", e ".join(parts[1:])


def is_exit_phrase(text: str, exit_phrases: list[str] | None = None) -> bool:
    from alexa_custom.config import _DEFAULT_EXIT_PHRASES

    words = exit_phrases if exit_phrases is not None else _DEFAULT_EXIT_PHRASES
    t = text.strip().lower()
    return any(t == w or t.startswith(w + " ") for w in words)


def normalize_confirm(text: str) -> str:
    t = text.strip().lower()
    yes_words = {"sì", "si", "sì", "yes", "ok", "confermo", "certo", "esatto", "giusto"}
    no_words = {"no", "nope", "annulla", "cancella", "stop", "no grazie"}
    for w in yes_words:
        if w in t:
            return "yes"
    for w in no_words:
        if w in t:
            return "no"
    return "no"
