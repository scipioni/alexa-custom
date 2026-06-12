"""LiveKit audio bridge for boards where PortAudio has no usable I/O.

On the Arduino Uno Q, PortAudio (sounddevice/PyAudio) has no working PipeWire
backend, so the LiveKit call path can't use it for playback or capture. These
classes bridge LiveKit's AudioStream/AudioSource to the native CLI tools that
do work here — ``paplay``/``aplay`` for output and ``parec`` for input.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)


class PaplayAudioOutput:
    """Audio output via paplay/aplay for boards where PortAudio has no output.

    Replaces devices.open_output() + player when pw_device is None.
    Starts one paplay process per remote track, lazily on the first frame so the
    sample rate and channel count are taken from the track itself.
    """

    SAMPLE_RATE = 48000
    CHANNELS = 1

    def __init__(self, on_frame_peak: Callable[[float], None] | None = None) -> None:
        self._tasks: list[asyncio.Task] = []
        self._on_frame_peak = on_frame_peak

    async def start(self) -> None:
        pass

    async def add_track(self, track) -> None:
        self._tasks.append(asyncio.create_task(self._pump_track(track)))

    async def remove_track(self, track) -> None:
        pass  # task ends when the AudioStream closes

    async def _pump_track(self, track) -> None:
        import shutil
        from livekit.rtc import AudioStream

        # Prefer paplay (PulseAudio compat socket, same package as parec which works).
        # Fall back to aplay -D pipewire if paplay is absent.
        tool = shutil.which("paplay") or shutil.which("aplay")
        if not tool:
            logger.error("Neither paplay nor aplay found — remote audio will be silent")
            return

        if "paplay" in tool:
            cmd = [
                tool,
                "--raw",
                f"--rate={self.SAMPLE_RATE}",
                f"--channels={self.CHANNELS}",
                "--format=s16le",
            ]
        else:
            cmd = [
                tool,
                "-D",
                "pipewire",
                "-f",
                "S16_LE",
                "-r",
                str(self.SAMPLE_RATE),
                "-c",
                str(self.CHANNELS),
            ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.debug(
            f"PaplayAudioOutput: {tool} started ({self.SAMPLE_RATE}Hz {self.CHANNELS}ch)"
        )
        # frame.data is a memoryview of int16 samples (s16le)
        stream = AudioStream(
            track, sample_rate=self.SAMPLE_RATE, num_channels=self.CHANNELS
        )
        try:
            async for event in stream:
                if proc.returncode is not None:
                    err = await proc.stderr.read()
                    if err:
                        logger.error(
                            f"PaplayAudioOutput: {tool} exited: {err.decode().strip()}"
                        )
                    break
                proc.stdin.write(bytes(event.frame.data))
                if self._on_frame_peak is not None:
                    samples = np.frombuffer(event.frame.data, dtype=np.int16)
                    if len(samples) > 0:
                        peak = float(np.max(np.abs(samples.astype(np.int32)))) / 32768.0
                        self._on_frame_peak(peak)
        except asyncio.CancelledError:
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
                await proc.wait()
            except Exception:
                pass
            logger.debug(f"PaplayAudioOutput: {tool} stopped (rc={proc.returncode})")

    async def aclose(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.debug("PaplayAudioOutput closed")


class ParecAudioCapture:
    """Microphone capture via parec for boards where PortAudio has no input devices.

    Feeds raw s16le PCM from parec into a LiveKit AudioSource so the call
    mic track works without PortAudio.  Matches the interface expected by
    LiveKitSessionManager (`.source` attribute + `async aclose()`).
    """

    SAMPLE_RATE = 48000
    CHANNELS = 1
    _FRAME_MS = 10  # 10 ms frames → 480 samples @ 48 kHz

    def __init__(self, capture_device: str | None = None) -> None:
        from livekit.rtc import AudioSource

        self._capture_device = capture_device
        self.source = AudioSource(self.SAMPLE_RATE, self.CHANNELS)
        self._proc: subprocess.Popen | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        import shutil

        tool = shutil.which("parec")
        if not tool:
            raise RuntimeError("parec not found — cannot open microphone for LiveKit")

        cmd = [
            tool,
            f"--rate={self.SAMPLE_RATE}",
            f"--channels={self.CHANNELS}",
            "--format=s16le",
            "--latency-msec=10",
        ]
        if self._capture_device:
            cmd.append(f"--device={self._capture_device}")

        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
        )

        frame_samples = self.SAMPLE_RATE * self._FRAME_MS // 1000
        frame_bytes = frame_samples * self.CHANNELS * 2  # s16le = 2 bytes/sample

        async def _pump() -> None:
            from livekit.rtc import AudioFrame

            assert self._proc and self._proc.stdout
            fd = self._proc.stdout.fileno()
            while True:
                try:
                    data = await asyncio.to_thread(os.read, fd, frame_bytes)
                except OSError:
                    break
                if not data:
                    break
                if len(data) < frame_bytes:
                    data = data + b"\x00" * (frame_bytes - len(data))
                frame = AudioFrame(
                    data=data,
                    sample_rate=self.SAMPLE_RATE,
                    num_channels=self.CHANNELS,
                    samples_per_channel=frame_samples,
                )
                await self.source.capture_frame(frame)

        self._task = asyncio.create_task(_pump())
        logger.debug("ParecAudioCapture started")

    async def aclose(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.to_thread(self._proc.wait)
            except Exception:
                pass
            self._proc = None
        logger.debug("ParecAudioCapture closed")


def calculate_peak(frame) -> float:
    """Calculate normalized peak level (0.0-1.0) from an AudioFrame."""
    samples = np.frombuffer(frame.data, dtype=np.int16)
    if len(samples) == 0:
        return 0.0
    # Use int32 for absolute to avoid int16 overflow at -32768
    return float(np.max(np.abs(samples.astype(np.int32)))) / 32768.0
