from __future__ import annotations

import logging
import threading
import time
from typing import Callable
import pulsectl

from alexa_custom.audio_hw import (
    enforce_audio_state,
    _restore_hw_pcm,
    pulse_session,
    set_output_volume,
    set_input_gain,
    invalidate_pipewire_device_cache,
    get_default_card_name,
)

logger = logging.getLogger(__name__)


class AudioWatcher(threading.Thread):
    """Daemon thread that monitors PipeWire events and enforces audio state."""

    def __init__(
        self,
        input_spec: str | None = None,
        output_spec: str | None = None,
        on_status_change: Callable[[bool, str], None] | None = None,
        output_volume: float = 0.5,
        input_gain: float = 1.0,
    ):
        super().__init__(daemon=True, name="audio-watcher")
        self.input_spec = input_spec
        self.output_spec = output_spec
        self.on_status_change = on_status_change
        self.output_volume = output_volume
        self.input_gain = input_gain
        self._stop = threading.Event()
        self.connected = False
        self.conn_type = "unknown"

    def stop(self):
        self._stop.set()

    def run(self):
        logger.info(
            f"Audio watcher started (target: {self.output_spec or get_default_card_name()})"
        )
        while not self._stop.is_set():
            try:
                with pulse_session("alexa-watcher") as pulse:
                    # Restore on open (the connection itself reset PCM); the
                    # session also restores again on close.
                    _restore_hw_pcm()
                    self._check_and_enforce(pulse)
                    pulse.event_mask_set("card", "sink", "source")
                    pulse.event_callback_set(lambda _: None)

                    last_enforce = 0.0
                    while not self._stop.is_set():
                        pulse.event_listen(timeout=2.0)
                        now = time.monotonic()
                        if now - last_enforce >= 1.0:
                            self._check_and_enforce(pulse)
                            last_enforce = now
            except Exception as e:
                if not self._stop.is_set():
                    logger.error(f"Audio watcher error: {e}")
                    time.sleep(2)

    def _check_and_enforce(self, pulse: pulsectl.Pulse):
        ok, conn = enforce_audio_state(pulse, self.input_spec, self.output_spec)
        if ok != self.connected or conn != self.conn_type:
            if ok and not self.connected:
                logger.info(f"Audio device {conn} connected and configured")
                _restore_hw_pcm()
                if self.output_volume > 0:
                    set_output_volume(pulse, self.output_spec, self.output_volume)
                set_input_gain(pulse, self.input_spec, self.input_gain)

            self.connected = ok
            self.conn_type = conn
            invalidate_pipewire_device_cache()
            if self.on_status_change:
                self.on_status_change(ok, conn)
