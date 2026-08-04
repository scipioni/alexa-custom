"""Pipeline-level integration tests for the STT recognition loop.

Tests the full run_stt_worker → _recognition_loop → on_stt_event path using
a ScriptedBackend (no real STT model) and a FakeProc (no real microphone).
Covers wake detection, command matching, with_wake gating, one-breath, direct
triggers, and the reply window.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import types
from collections import deque
from typing import Any

import pytest

import alexa_custom.stt as _stt_module
from alexa_custom.actions import ActionEntry, TelegramClient, registry
from alexa_custom.config import (
    ActionsConfig,
    AudioConfig,
    RecognitionConfig,
    STTConfig,
    Trigger,
)
from alexa_custom.stt import start_stt_thread
from alexa_custom.stt_backends import STTBackend

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CHUNK = 4096  # bytes per audio chunk (matches stt_gating._CHUNK)
_CHUNKS_PER_EMIT = 3  # how many chunks ScriptedBackend consumes before endpoint


# ---------------------------------------------------------------------------
# FakeProc — endless stream of silent PCM chunks via os.pipe
# ---------------------------------------------------------------------------


class FakeProc:
    """Streams silent PCM chunks into an os.pipe so the recognition loop never blocks."""

    def __init__(self, total_chunks: int = 500) -> None:
        r_fd, self._w_fd = os.pipe()
        self.stdout = os.fdopen(r_fd, "rb", buffering=0)
        self._thread = threading.Thread(
            target=self._fill, args=(total_chunks,), daemon=True
        )
        self._thread.start()

    def _fill(self, total_chunks: int) -> None:
        silence = bytes(_CHUNK)
        try:
            with os.fdopen(self._w_fd, "wb", buffering=0) as f:
                for _ in range(total_chunks):
                    f.write(silence)
        except BrokenPipeError:
            pass

    def poll(self) -> None:
        return None  # always alive from loop's perspective


# ---------------------------------------------------------------------------
# ScriptedBackend — delivers pre-canned transcripts, ignores audio content
# ---------------------------------------------------------------------------


class ScriptedBackend(STTBackend):
    """STTBackend that pops transcripts from a FIFO queue after _CHUNKS_PER_EMIT chunks.

    Fires endpoint=True when the next transcript is ready. After the last
    transcript is delivered, sets stop_event so run_stt_worker exits cleanly.
    recreate() is a no-op so reply-window grammar switches are transparent.
    """

    def __init__(self, script: list[str], stop_event: threading.Event) -> None:
        self._queue: deque[str] = deque(script)
        self._stop_event = stop_event
        self._chunks = 0
        self._pending: str = ""

    def accept_waveform(self, data: bytes) -> bool:
        self._chunks += 1
        if self._chunks >= _CHUNKS_PER_EMIT and self._queue:
            self._pending = self._queue.popleft()
            self._chunks = 0
            if not self._queue:
                # All transcripts consumed — signal worker to stop after this dispatch
                threading.Timer(0.3, self._stop_event.set).start()
            return True
        return False

    def text(self) -> str:
        t = self._pending
        self._pending = ""
        return t

    def partial_text(self) -> str:
        return ""

    def reset(self) -> None:
        self._chunks = 0

    def finalize(self) -> str:
        return ""

    def recreate(self, grammar: str | None = None) -> None:
        # No-op: next queued transcript is served regardless of grammar
        pass


# ---------------------------------------------------------------------------
# run_pipeline — full harness
# ---------------------------------------------------------------------------


def run_pipeline(
    script: list[str],
    config: ActionsConfig,
    timeout: float = 5.0,
    silence_beep: bool = True,
    mqtt_client: Any = None,
    mqtt_trigger_command: str | None = None,
) -> list[tuple[str, dict]]:
    """Drive the full recognition pipeline with scripted transcripts.

    Monkeypatches start_capture, get_stt_backend, TTS engine and the wake beep
    so no real hardware, model, or network is needed. Returns all on_stt_event
    calls in order.

    silence_beep=True replaces play_wake_beep_async with a no-op: a real tone
    would set the _playback_active gate and make the loop drop FakeProc chunks,
    starving the ScriptedBackend. Pass False only to test the beep path itself.

    mqtt_trigger_command, if given, is delivered through mqtt_client's
    set_on_command() callback (as a real MQTT trigger/run message would be)
    from a background thread once the STT worker registers it, then stops the
    pipeline — script-driven voice matching and MQTT-driven matching are
    mutually exclusive in a single run_pipeline call, so pass an empty script.
    """
    events: list[tuple[str, dict]] = []
    stop_event = threading.Event()
    ready_event = threading.Event()

    scripted = ScriptedBackend(script, stop_event)
    fake_proc = FakeProc(total_chunks=500)

    trigger_thread = None
    if mqtt_trigger_command is not None:
        assert mqtt_client is not None, "mqtt_trigger_command needs an mqtt_client"

        def _fire_mqtt_trigger() -> None:
            deadline = time.monotonic() + timeout
            while getattr(mqtt_client, "_callback", None) is None:
                if time.monotonic() > deadline:
                    return
                time.sleep(0.01)
            asyncio.run(mqtt_client._callback({"command": mqtt_trigger_command}))
            stop_event.set()

        trigger_thread = threading.Thread(target=_fire_mqtt_trigger, daemon=True)
        trigger_thread.start()

    # --- monkeypatches ---
    orig_start_capture = _stt_module.start_capture
    orig_get_backend = _stt_module.get_stt_backend
    orig_beep = _stt_module.play_wake_beep_async

    def _fake_start_capture(source: Any, channels: int = 1, config: Any = None):
        return fake_proc

    def _fake_get_backend(stt_config: Any, keywords: Any = None, grammar: Any = None):
        return scripted

    _stt_module.start_capture = _fake_start_capture
    _stt_module.get_stt_backend = _fake_get_backend
    if silence_beep:
        _stt_module.play_wake_beep_async = lambda name: None

    # Silence TTS: handle_ask does `from alexa_custom.tts import get_engine`
    # at call time, so patch the source module directly.
    import alexa_custom.tts as _tts_module

    _orig_get_engine = _tts_module.get_engine
    _mock_engine = types.SimpleNamespace(say=lambda *a, **kw: None)
    _tts_module.get_engine = lambda: _mock_engine

    def _collect(event: str, data: dict) -> None:
        events.append((event, data))

    try:
        thread = start_stt_thread(
            config=config,
            stop_event=stop_event,
            telegram_client=TelegramClient(),
            livekit_connect_fn=None,
            livekit_connected_flag=threading.Event(),
            on_stt_event=_collect,
            stt_ready_event=ready_event,
            mqtt_client=mqtt_client,
        )
        thread.join(timeout=timeout)
    finally:
        _stt_module.start_capture = orig_start_capture
        _stt_module.get_stt_backend = orig_get_backend
        _stt_module.play_wake_beep_async = orig_beep
        _tts_module.get_engine = _orig_get_engine
        if trigger_thread is not None:
            trigger_thread.join(timeout=1.0)

    return events


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _log_action() -> ActionEntry:
    return ActionEntry(type="log", params={"message": "ok"})


def _make_config(
    triggers: list[Trigger],
    wake_words: list[str] | None = None,
    wake_window: float = 8.0,
    vad_silence_ms: int = 900,
) -> ActionsConfig:
    return ActionsConfig(
        wake_words=wake_words or ["ehi galileo"],
        triggers=triggers,
        recognition=RecognitionConfig(wake_window=wake_window),
        stt=STTConfig(vad_silence_ms=vad_silence_ms),
        audio=AudioConfig(),
    )


def _gated(commands: list[str], actions=None) -> Trigger:
    a = actions or [_log_action()]
    return Trigger(commands=commands, phrase=commands[0], actions=a, with_wake=True)


def _direct(commands: list[str], actions=None) -> Trigger:
    a = actions or [_log_action()]
    return Trigger(commands=commands, phrase=commands[0], actions=a, with_wake=False)


def _event_names(events: list[tuple[str, dict]]) -> list[str]:
    return [e for e, _ in events]


# ---------------------------------------------------------------------------
# 2. Core Scenario Tests
# ---------------------------------------------------------------------------


class TestTwoStepWakeCommand:
    def test_wake_then_matched(self, caplog):
        import logging

        caplog.set_level(logging.INFO)
        config = _make_config([_gated(["che ore sono"])])
        events = run_pipeline(["ehi galileo", "che ore sono"], config)
        names = _event_names(events)
        assert "wake" in names, f"no wake event; got {names}"
        assert "matched" in names, f"no matched event; got {names}"
        assert any(
            "Command: 'che ore sono' → 'che ore sono'" in r.message
            for r in caplog.records
        )

    def test_wake_precedes_match(self):
        config = _make_config([_gated(["che ore sono"])])
        events = run_pipeline(["ehi galileo", "che ore sono"], config)
        names = _event_names(events)
        wake_idx = next(i for i, n in enumerate(names) if n == "wake")
        match_idx = next(i for i, n in enumerate(names) if n == "matched")
        assert wake_idx < match_idx, "wake should precede matched"


class TestTwoStepWakeNoMatch:
    def test_wake_present_no_matched(self):
        config = _make_config([_gated(["che ore sono"])])
        events = run_pipeline(["ehi galileo", "blah blah blah"], config)
        names = _event_names(events)
        assert "wake" in names, f"no wake event; got {names}"
        assert "matched" not in names, f"unexpected match; got {names}"


class TestOneBreath:
    def test_one_breath_fires_wake_and_match(self):
        config = _make_config([_gated(["che ore sono"])])
        events = run_pipeline(["ehi galileo che ore sono"], config)
        names = _event_names(events)
        assert "wake" in names, f"no wake event; got {names}"
        assert "matched" in names, f"no matched event; got {names}"


class TestDirectTrigger:
    def test_direct_fires_without_wake(self, caplog):
        import logging

        caplog.set_level(logging.INFO)
        config = _make_config([_direct(["chiama stefano"])])
        events = run_pipeline(["chiama stefano"], config)
        names = _event_names(events)
        assert "matched" in names, f"no matched event; got {names}"
        assert "wake" not in names, f"unexpected wake event; got {names}"
        assert any(
            "Direct: 'chiama stefano' → 'chiama stefano'" in r.message
            for r in caplog.records
        )


class TestGatedTriggerNoWake:
    def test_gated_suppressed_without_wake(self):
        config = _make_config([_gated(["che ore sono"])])
        events = run_pipeline(["che ore sono"], config)
        names = _event_names(events)
        assert "matched" not in names, f"unexpected match without wake; got {names}"


# ---------------------------------------------------------------------------
# 3. Reply Window Tests
# ---------------------------------------------------------------------------


def _ask_trigger(with_wake: bool = True) -> Trigger:
    """'chiama stefano' ask trigger with si/no on_reply."""
    on_reply = [
        Trigger(
            commands=["si", "sì"],
            phrase="si",
            actions=[_log_action()],
            with_wake=True,
        ),
        Trigger(
            commands=["no"],
            phrase="no",
            actions=[_log_action()],
            with_wake=True,
        ),
    ]
    ask_action = ActionEntry(
        type="ask",
        params={
            "text": "Vuoi chiamare Stefano?",
            "lang": "it-IT",
            "timeout": 3.0,
        },
        on_reply=on_reply,
    )
    return Trigger(
        commands=["chiama stefano"],
        phrase="chiama stefano",
        actions=[ask_action],
        with_wake=with_wake,
    )


class TestReplyWindowMatch:
    def test_wake_command_and_reply_matched(self):
        config = _make_config([_ask_trigger()])
        events = run_pipeline(["ehi galileo", "chiama stefano", "si"], config)
        names = _event_names(events)
        assert "wake" in names, f"no wake; got {names}"
        matched = [(e, d) for e, d in events if e == "matched"]
        assert len(matched) >= 2, f"expected ≥2 matched events; got {names}"
        triggers = [d.get("phrase", "") for _, d in matched]
        assert any("chiama" in t for t in triggers), (
            f"chiama trigger missing; {triggers}"
        )
        assert any(t == "si" for t in triggers), f"si reply missing; {triggers}"

    def test_reply_match_order(self):
        config = _make_config([_ask_trigger()])
        events = run_pipeline(["ehi galileo", "chiama stefano", "si"], config)
        matched = [(i, d) for i, (e, d) in enumerate(events) if e == "matched"]
        assert len(matched) >= 2
        first_trigger = matched[0][1].get("phrase", "")
        second_trigger = matched[1][1].get("phrase", "")
        assert "chiama" in first_trigger, (
            f"first match should be chiama; got {first_trigger}"
        )
        assert second_trigger == "si", (
            f"second match should be si; got {second_trigger}"
        )


class TestReplyWindowTimeout:
    def test_no_second_match_on_timeout(self):
        # Only wake + command, no reply utterance → reply window times out
        config = _make_config([_ask_trigger()])
        # Short ask timeout so test doesn't block: patch the trigger's timeout
        ask_trigger = _ask_trigger()
        ask_trigger.actions[0].params["timeout"] = 0.5
        config = _make_config([ask_trigger])
        events = run_pipeline(["ehi galileo", "chiama stefano"], config, timeout=8.0)
        names = _event_names(events)
        assert "wake" in names
        matched = [(e, d) for e, d in events if e == "matched"]
        # First matched fires for "chiama stefano"
        assert len(matched) >= 1
        triggers = [d.get("phrase", "") for _, d in matched]
        # No "si" or "no" reply matched
        assert not any(t in ("si", "no") for t in triggers), (
            f"unexpected reply match; triggers={triggers}"
        )


# ---------------------------------------------------------------------------
# 4. System direct triggers (from conf.example/actions/system.yaml)
# ---------------------------------------------------------------------------


class TestSystemDirectTriggers:
    """Direct triggers (with_wake=False) — fire without a wake word. One case
    per canonical phrase and per alias proves the alias list resolves."""

    @pytest.mark.parametrize(
        "commands, utterance",
        [
            (["che ore sono", "che ora è"], "che ore sono"),
            (["che ore sono", "che ora è"], "che ora è"),
            (["che giorno è", "che giorno è oggi"], "che giorno è"),
            (["che giorno è", "che giorno è oggi"], "che giorno è oggi"),
            (["svegliati adesso", "attiva ascolto"], "svegliati adesso"),
            (["svegliati adesso", "attiva ascolto"], "attiva ascolto"),
        ],
    )
    def test_direct_trigger_matches(self, commands, utterance):
        config = _make_config([_direct(commands)])
        events = run_pipeline([utterance], config)
        assert "matched" in _event_names(events)


# ---------------------------------------------------------------------------
# 5. System gated triggers (from conf.example/actions/system.yaml)
# ---------------------------------------------------------------------------


class TestGatedTriggers:
    """Gated triggers — require a wake word first. Covers the canonical phrases
    and aliases shipped in conf.example (system.yaml + user.yaml, including the
    commented domotica/assistance examples)."""

    @pytest.mark.parametrize(
        "commands, utterance",
        [
            (["dimmi qualcosa"], "dimmi qualcosa"),
            (["riavvia"], "riavvia"),
            (["volume basso"], "volume basso"),
            (["volume medio"], "volume medio"),
            (["volume alto"], "volume alto"),
            (["alza il volume"], "alza il volume"),
            (["abbassa il volume"], "abbassa il volume"),
            (["dormi", "smetti di ascoltare"], "dormi"),
            (["dormi", "smetti di ascoltare"], "smetti di ascoltare"),
            (["come stai"], "come stai"),
            (
                ["registra campione", "test audio", "registra audio"],
                "registra campione",
            ),
            (["registra campione", "test audio", "registra audio"], "test audio"),
            (["accendi la luce"], "accendi la luce"),
            # Commented domotica examples from user.yaml.
            (["di qualcosa"], "di qualcosa"),
            (["suona"], "suona"),
            (["connettiti"], "connettiti"),
            (["spegni le luci"], "spegni le luci"),
            (["alza il riscaldamento"], "alza il riscaldamento"),
            (["abbassa il riscaldamento"], "abbassa il riscaldamento"),
            (["alza le tapparelle"], "alza le tapparelle"),
            (["abbassa le tapparelle"], "abbassa le tapparelle"),
            (["accendi la tv"], "accendi la tv"),
            (["spegni la tv"], "spegni la tv"),
            (["buonanotte"], "buonanotte"),
            # Commented assistance examples from user.yaml.
            (["chiama il medico"], "chiama il medico"),
            (["chiama i soccorsi"], "chiama i soccorsi"),
            (["non sto bene"], "non sto bene"),
            (["sono caduto"], "sono caduto"),
            (["chiama la famiglia"], "chiama la famiglia"),
            (["ho preso le medicine"], "ho preso le medicine"),
            (["non ho preso le medicine"], "non ho preso le medicine"),
            (["sto bene grazie"], "sto bene grazie"),
        ],
    )
    def test_gated_trigger_matches(self, commands, utterance):
        config = _make_config([_gated(commands)])
        events = run_pipeline(["ehi galileo", utterance], config)
        assert "matched" in _event_names(events)


# ---------------------------------------------------------------------------
# 6. User active triggers (from conf.example/actions/user.yaml)
# ---------------------------------------------------------------------------


class TestUserActiveTriggers:
    """Active (uncommented) triggers from user.yaml — ask/reply flows and
    custom wake words (the plain gated phrases are covered by TestGatedTriggers)."""

    def test_chiama_stefano_direct_no_reply(self):
        ask_trigger = _ask_trigger(with_wake=False)
        ask_trigger.actions[0].params["timeout"] = 0.5
        config = _make_config([ask_trigger])
        events = run_pipeline(["chiama Stefano"], config, timeout=8.0)
        # No real wake word fired (the ask action emits wake "(reply)" — exclude that)
        real_wakes = [
            d for e, d in events if e == "wake" and d.get("word") != "(reply)"
        ]
        assert not real_wakes, f"unexpected real wake: {real_wakes}"
        assert "matched" in _event_names(events)

    def test_chiama_stefano_direct_reply_no(self):
        ask_trigger = _ask_trigger(with_wake=False)
        config = _make_config([ask_trigger])
        events = run_pipeline(["chiama Stefano", "no"], config)
        matched = [d for e, d in events if e == "matched"]
        triggers = [d.get("phrase", "") for d in matched]
        assert any("chiama" in t.lower() for t in triggers)
        assert any(t == "no" for t in triggers)

    def test_chiama_stefano_reply_va_bene(self):
        # "va bene" is an alias in on_reply["si"] commands list
        on_reply = [
            Trigger(
                commands=["si", "sì", "va bene", "certo", "ok", "dai"],
                phrase="si",
                actions=[_log_action()],
                with_wake=True,
            ),
            Trigger(
                commands=["no", "no grazie", "annulla"],
                phrase="no",
                actions=[_log_action()],
                with_wake=True,
            ),
        ]
        ask = ActionEntry(
            type="ask",
            params={"text": "Vuoi chiamare Stefano?", "lang": "it-IT", "timeout": 3.0},
            on_reply=on_reply,
        )
        t = Trigger(
            commands=["chiama Stefano"],
            phrase="chiama Stefano",
            actions=[ask],
            with_wake=False,
        )
        config = _make_config([t])
        events = run_pipeline(["chiama Stefano", "va bene"], config)
        triggers = [d.get("phrase", "") for e, d in events if e == "matched"]
        assert any(t == "si" for t in triggers), (
            f"'va bene' should match 'si' trigger; got {triggers}"
        )

    @pytest.mark.parametrize(
        "wake_words, wake_utterance",
        [
            # "aiuto"/"aiutami" are both wake words and trigger commands.
            (["aiuto", "aiutami"], "aiuto"),
            (["aiuto", "aiutami"], "aiutami"),
            (["ehi galileo", "ascolta assistente"], "ascolta assistente"),
        ],
    )
    def test_custom_wake_word_then_command(self, wake_words, wake_utterance):
        config = _make_config(
            triggers=[_gated(["che ore sono"])],
            wake_words=wake_words,
        )
        events = run_pipeline([wake_utterance, "che ore sono"], config)
        names = _event_names(events)
        assert "wake" in names
        assert "matched" in names


class TestAsyncWakeBeep:
    def test_dispatch_not_blocked_by_tone(self):
        """The confirmation tone must not delay dispatch (async beep).

        The tone blocks on an event the test releases only AFTER the pipeline
        run: with the old synchronous beep the recognition thread would hang
        inside the tone before dispatching and no 'matched' event would arrive
        within the harness timeout.
        """
        from unittest.mock import patch

        tone_started = threading.Event()
        release_tone = threading.Event()

        def blocking_tone(name):
            tone_started.set()
            release_tone.wait(timeout=15)

        config = _make_config([_direct(["chiama stefano"])])
        try:
            with patch("alexa_custom.audio_ops.play_tone", side_effect=blocking_tone):
                events = run_pipeline(["chiama stefano"], config, silence_beep=False)
        finally:
            release_tone.set()
        names = _event_names(events)
        assert "matched" in names, (
            f"no matched event while tone still playing; got {names}"
        )
        assert tone_started.is_set(), "tone playback was never started"


class _FakeMqttClient:
    """Records publish_threadsafe() calls to the state topic; no real broker."""

    topic_prefix = "alexa"
    node_id = "test-node"

    def __init__(self) -> None:
        self.states: list[str] = []
        self._callback = None

    def publish_threadsafe(self, topic, payload, retain=False, loop=None):
        if topic == f"{self.topic_prefix}/{self.node_id}/state":
            self.states.append(payload)

    async def publish(self, topic, payload, retain=False):
        if topic == f"{self.topic_prefix}/{self.node_id}/state":
            self.states.append(payload)

    def set_on_command(self, callback):
        self._callback = callback


class TestOperativeStatePublish:
    def test_start_published_once_before_idle(self):
        """A single 'start' state is published as capture comes up, ahead of
        the first 'idle' — the daemon's one-time "I'm operative" signal."""
        mqtt_client = _FakeMqttClient()
        config = _make_config([_direct(["chiama stefano"])])
        run_pipeline(["chiama stefano"], config, mqtt_client=mqtt_client)

        assert mqtt_client.states[0] == "start"
        assert mqtt_client.states.count("start") == 1


class TestMqttTriggerRegexEndToEnd:
    """MQTT trigger/run with a command_regex-matched trigger, end to end:
    mqtt.py's callback shape -> stt.py's _on_mqtt_command -> match_trigger_regex
    -> substitute_action_params -> dispatch. Reproduces onvif_sua sending
    'caduta_bagno' on hub/2q/trigger/run (mirrored locally to trigger/run)."""

    def test_captured_group_substituted_into_action_params(self):
        received: list[dict] = []

        @registry.register("_capture_test")
        async def _capture(action, **_):
            received.append(action.params)

        try:
            trigger = Trigger(
                commands=["caduta"],
                command_regex=["caduta_(?P<stanza>.+)"],
                actions=[
                    ActionEntry(
                        type="_capture_test",
                        params={"text": "Caduta rilevata in <stanza>"},
                    )
                ],
                with_wake=False,
            )
            config = _make_config([trigger])
            mqtt_client = _FakeMqttClient()

            run_pipeline(
                [],
                config,
                mqtt_client=mqtt_client,
                mqtt_trigger_command="caduta_bagno",
            )
        finally:
            registry._handlers.pop("_capture_test", None)

        assert received == [{"text": "Caduta rilevata in bagno"}]
