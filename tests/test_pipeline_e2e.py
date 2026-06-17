"""Pipeline-level integration tests for the STT recognition loop.

Tests the full run_stt_worker → _recognition_loop → on_stt_event path using
a ScriptedBackend (no real STT model) and a FakeProc (no real microphone).
Covers wake detection, command matching, with_wake gating, one-breath, direct
triggers, and the reply window.
"""

from __future__ import annotations

import os
import threading
import types
from collections import deque
from typing import Any


import alexa_custom.stt as _stt_module
from alexa_custom.actions import ActionEntry, TelegramClient
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
) -> list[tuple[str, dict]]:
    """Drive the full recognition pipeline with scripted transcripts.

    Monkeypatches start_capture, get_stt_backend, and TTS engine so no real
    hardware, model, or network is needed. Returns all on_stt_event calls in
    order.
    """
    events: list[tuple[str, dict]] = []
    stop_event = threading.Event()
    ready_event = threading.Event()

    scripted = ScriptedBackend(script, stop_event)
    fake_proc = FakeProc(total_chunks=500)

    # --- monkeypatches ---
    orig_start_capture = _stt_module.start_capture
    orig_get_backend = _stt_module.get_stt_backend

    def _fake_start_capture(source: Any, channels: int = 1):
        return fake_proc

    def _fake_get_backend(stt_config: Any):
        return scripted

    _stt_module.start_capture = _fake_start_capture
    _stt_module.get_stt_backend = _fake_get_backend

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
        )
        thread.join(timeout=timeout)
    finally:
        _stt_module.start_capture = orig_start_capture
        _stt_module.get_stt_backend = orig_get_backend
        _tts_module.get_engine = _orig_get_engine

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
    """Direct triggers (with_wake=False) from system.yaml — fire without wake word."""

    def test_che_ore_sono(self):
        config = _make_config([_direct(["che ore sono", "che ora è"])])
        events = run_pipeline(["che ore sono"], config)
        assert "matched" in _event_names(events)

    def test_che_ora_e_alias(self):
        config = _make_config([_direct(["che ore sono", "che ora è"])])
        events = run_pipeline(["che ora è"], config)
        assert "matched" in _event_names(events)

    def test_che_giorno_e(self):
        config = _make_config([_direct(["che giorno è", "che giorno è oggi"])])
        events = run_pipeline(["che giorno è"], config)
        assert "matched" in _event_names(events)

    def test_che_giorno_e_alias(self):
        config = _make_config([_direct(["che giorno è", "che giorno è oggi"])])
        events = run_pipeline(["che giorno è oggi"], config)
        assert "matched" in _event_names(events)

    def test_svegliati_adesso(self):
        config = _make_config([_direct(["svegliati adesso", "attiva ascolto"])])
        events = run_pipeline(["svegliati adesso"], config)
        assert "matched" in _event_names(events)

    def test_attiva_ascolto_alias(self):
        config = _make_config([_direct(["svegliati adesso", "attiva ascolto"])])
        events = run_pipeline(["attiva ascolto"], config)
        assert "matched" in _event_names(events)


# ---------------------------------------------------------------------------
# 5. System gated triggers (from conf.example/actions/system.yaml)
# ---------------------------------------------------------------------------


class TestSystemGatedTriggers:
    """Gated triggers from system.yaml — require a wake word first."""

    def test_dimmi_qualcosa(self):
        config = _make_config([_gated(["dimmi qualcosa"])])
        events = run_pipeline(["ehi galileo", "dimmi qualcosa"], config)
        assert "matched" in _event_names(events)

    def test_riavvia(self):
        config = _make_config([_gated(["riavvia"])])
        events = run_pipeline(["ehi galileo", "riavvia"], config)
        assert "matched" in _event_names(events)

    def test_volume_basso(self):
        config = _make_config([_gated(["volume basso"])])
        events = run_pipeline(["ehi galileo", "volume basso"], config)
        assert "matched" in _event_names(events)

    def test_volume_medio(self):
        config = _make_config([_gated(["volume medio"])])
        events = run_pipeline(["ehi galileo", "volume medio"], config)
        assert "matched" in _event_names(events)

    def test_volume_alto(self):
        config = _make_config([_gated(["volume alto"])])
        events = run_pipeline(["ehi galileo", "volume alto"], config)
        assert "matched" in _event_names(events)

    def test_alza_il_volume(self):
        config = _make_config([_gated(["alza il volume"])])
        events = run_pipeline(["ehi galileo", "alza il volume"], config)
        assert "matched" in _event_names(events)

    def test_abbassa_il_volume(self):
        config = _make_config([_gated(["abbassa il volume"])])
        events = run_pipeline(["ehi galileo", "abbassa il volume"], config)
        assert "matched" in _event_names(events)

    def test_dormi(self):
        config = _make_config([_gated(["dormi", "smetti di ascoltare"])])
        events = run_pipeline(["ehi galileo", "dormi"], config)
        assert "matched" in _event_names(events)

    def test_smetti_di_ascoltare_alias(self):
        config = _make_config([_gated(["dormi", "smetti di ascoltare"])])
        events = run_pipeline(["ehi galileo", "smetti di ascoltare"], config)
        assert "matched" in _event_names(events)

    def test_come_stai(self):
        config = _make_config([_gated(["come stai"])])
        events = run_pipeline(["ehi galileo", "come stai"], config)
        assert "matched" in _event_names(events)

    def test_registra_campione(self):
        config = _make_config(
            [_gated(["registra campione", "test audio", "registra audio"])]
        )
        events = run_pipeline(["ehi galileo", "registra campione"], config)
        assert "matched" in _event_names(events)

    def test_test_audio_alias(self):
        config = _make_config(
            [_gated(["registra campione", "test audio", "registra audio"])]
        )
        events = run_pipeline(["ehi galileo", "test audio"], config)
        assert "matched" in _event_names(events)


# ---------------------------------------------------------------------------
# 6. User active triggers (from conf.example/actions/user.yaml)
# ---------------------------------------------------------------------------


class TestUserActiveTriggers:
    """Active (uncommented) triggers from user.yaml."""

    def test_accendi_la_luce(self):
        config = _make_config([_gated(["accendi la luce"])])
        events = run_pipeline(["ehi galileo", "accendi la luce"], config)
        assert "matched" in _event_names(events)

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

    def test_aiuto_wake_word_then_command(self):
        # "aiuto" is both a wake word and a trigger command in user.yaml
        config = _make_config(
            triggers=[_gated(["che ore sono"])],
            wake_words=["aiuto", "aiutami"],
        )
        events = run_pipeline(["aiuto", "che ore sono"], config)
        names = _event_names(events)
        assert "wake" in names
        assert "matched" in names

    def test_aiutami_wake_word(self):
        config = _make_config(
            triggers=[_gated(["che ore sono"])],
            wake_words=["aiuto", "aiutami"],
        )
        events = run_pipeline(["aiutami", "che ore sono"], config)
        names = _event_names(events)
        assert "wake" in names
        assert "matched" in names

    def test_ascolta_assistente_wake_word(self):
        config = _make_config(
            triggers=[_gated(["che ore sono"])],
            wake_words=["ehi galileo", "ascolta assistente"],
        )
        events = run_pipeline(["ascolta assistente", "che ore sono"], config)
        names = _event_names(events)
        assert "wake" in names
        assert "matched" in names


# ---------------------------------------------------------------------------
# 7. Commented user.yaml examples (domotica + assistenza anziani)
#    These show that the commented triggers work when uncommented.
# ---------------------------------------------------------------------------


class TestCommentedUserExamples:
    """Commented triggers from user.yaml — verify they match when enabled."""

    def test_di_qualcosa(self):
        config = _make_config([_gated(["di qualcosa"])])
        events = run_pipeline(["ehi galileo", "di qualcosa"], config)
        assert "matched" in _event_names(events)

    def test_suona(self):
        config = _make_config([_gated(["suona"])])
        events = run_pipeline(["ehi galileo", "suona"], config)
        assert "matched" in _event_names(events)

    def test_connettiti(self):
        config = _make_config([_gated(["connettiti"])])
        events = run_pipeline(["ehi galileo", "connettiti"], config)
        assert "matched" in _event_names(events)

    def test_spegni_le_luci(self):
        config = _make_config([_gated(["spegni le luci"])])
        events = run_pipeline(["ehi galileo", "spegni le luci"], config)
        assert "matched" in _event_names(events)

    def test_alza_il_riscaldamento(self):
        config = _make_config([_gated(["alza il riscaldamento"])])
        events = run_pipeline(["ehi galileo", "alza il riscaldamento"], config)
        assert "matched" in _event_names(events)

    def test_abbassa_il_riscaldamento(self):
        config = _make_config([_gated(["abbassa il riscaldamento"])])
        events = run_pipeline(["ehi galileo", "abbassa il riscaldamento"], config)
        assert "matched" in _event_names(events)

    def test_alza_le_tapparelle(self):
        config = _make_config([_gated(["alza le tapparelle"])])
        events = run_pipeline(["ehi galileo", "alza le tapparelle"], config)
        assert "matched" in _event_names(events)

    def test_abbassa_le_tapparelle(self):
        config = _make_config([_gated(["abbassa le tapparelle"])])
        events = run_pipeline(["ehi galileo", "abbassa le tapparelle"], config)
        assert "matched" in _event_names(events)

    def test_accendi_la_tv(self):
        config = _make_config([_gated(["accendi la tv"])])
        events = run_pipeline(["ehi galileo", "accendi la tv"], config)
        assert "matched" in _event_names(events)

    def test_spegni_la_tv(self):
        config = _make_config([_gated(["spegni la tv"])])
        events = run_pipeline(["ehi galileo", "spegni la tv"], config)
        assert "matched" in _event_names(events)

    def test_buonanotte(self):
        config = _make_config([_gated(["buonanotte"])])
        events = run_pipeline(["ehi galileo", "buonanotte"], config)
        assert "matched" in _event_names(events)

    # Assistenza anziani
    def test_chiama_il_medico(self):
        config = _make_config([_gated(["chiama il medico"])])
        events = run_pipeline(["ehi galileo", "chiama il medico"], config)
        assert "matched" in _event_names(events)

    def test_chiama_i_soccorsi(self):
        config = _make_config([_gated(["chiama i soccorsi"])])
        events = run_pipeline(["ehi galileo", "chiama i soccorsi"], config)
        assert "matched" in _event_names(events)

    def test_non_sto_bene(self):
        config = _make_config([_gated(["non sto bene"])])
        events = run_pipeline(["ehi galileo", "non sto bene"], config)
        assert "matched" in _event_names(events)

    def test_sono_caduto(self):
        config = _make_config([_gated(["sono caduto"])])
        events = run_pipeline(["ehi galileo", "sono caduto"], config)
        assert "matched" in _event_names(events)

    def test_chiama_la_famiglia(self):
        config = _make_config([_gated(["chiama la famiglia"])])
        events = run_pipeline(["ehi galileo", "chiama la famiglia"], config)
        assert "matched" in _event_names(events)

    def test_ho_preso_le_medicine(self):
        config = _make_config([_gated(["ho preso le medicine"])])
        events = run_pipeline(["ehi galileo", "ho preso le medicine"], config)
        assert "matched" in _event_names(events)

    def test_non_ho_preso_le_medicine(self):
        config = _make_config([_gated(["non ho preso le medicine"])])
        events = run_pipeline(["ehi galileo", "non ho preso le medicine"], config)
        assert "matched" in _event_names(events)

    def test_sto_bene_grazie(self):
        config = _make_config([_gated(["sto bene grazie"])])
        events = run_pipeline(["ehi galileo", "sto bene grazie"], config)
        assert "matched" in _event_names(events)
