"""GStreamer-based audio capture backend for the STT pipeline.

Provides GStreamerCapture — a drop-in replacement for subprocess.Popen that
routes microphone audio through a GStreamer pipeline before it reaches Vosk.
The pipeline inserts webrtcdsp (WebRTC APM) for noise suppression, automatic
gain control, and high-pass filtering, then writes s16le 16 kHz mono PCM into
an OS pipe that the existing stt_gating.py read path consumes unchanged.

Usage: selected via stt.capture_backend: gstreamer in config.yaml.
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)


def _build_pipeline_string(
    source_name: str | None,
    config,  # GStreamerCaptureConfig
    write_fd: int,
) -> str:
    use_pipewire = config.source == "pipewiresrc"
    src_element = "pipewiresrc" if use_pipewire else "pulsesrc"

    if use_pipewire:
        device_prop = (
            f' target-object="{source_name}"' if source_name else ""
        )
    else:
        device_prop = (
            f' device="{source_name}"' if source_name else ""
        )

    latency = "" if use_pipewire else " latency-time=10000 buffer-time=20000"

    # pipewiresrc lets GStreamer negotiate caps all the way to PipeWire, which
    # then can't resample internally on this board. Pin the source to its native
    # format so GStreamer's audioconvert/audioresample handle the conversion.
    native_caps = (
        " ! audio/x-raw,format=S16LE,rate=48000" if use_pipewire else ""
    )

    ns_level = max(0, min(3, config.noise_suppression_level))
    target_dbfs = max(0, min(31, abs(config.agc_target_level_dbfs)))
    compression_db = max(0, min(90, config.agc_compression_gain_db))

    webrtc_props = (
        f"noise-suppression={str(config.noise_suppression).lower()}"
        f" noise-suppression-level={ns_level}"
        f" gain-control={str(config.agc).lower()}"
        f" target-level-dbfs={target_dbfs}"
        f" compression-gain-db={compression_db}"
        f" high-pass-filter={str(config.high_pass_filter).lower()}"
        " echo-cancel=false"
        " voice-detection=false"
    )

    compressor_stage = ""
    if config.compressor:
        threshold = max(0.0, min(1.0, config.compressor_threshold))
        ratio = max(1.0, config.compressor_ratio)
        compressor_stage = (
            f" ! audiodynamic mode=compressor"
            f" threshold={threshold:.4f}"
            f" ratio={ratio:.2f}"
            " characteristics=soft-knee"
        )

    return (
        f"{src_element}{device_prop}{latency}"
        f"{native_caps}"
        " ! audioconvert"
        " ! audioresample"
        " ! audio/x-raw,format=S16LE,rate=16000,channels=1"
        f" ! webrtcdsp {webrtc_props}"
        f"{compressor_stage}"
        " ! audioconvert"
        " ! audio/x-raw,format=S16LE,rate=16000,channels=1"
        " ! queue max-size-buffers=100 leaky=downstream"
        f" ! fdsink fd={write_fd} sync=false"
    )


class GStreamerCapture:
    """Duck-typed subprocess.Popen replacement backed by a GStreamer pipeline.

    Exposes .stdout (pipe read-end), .poll(), .terminate(), and .wait() so
    that stt_gating._iter_gated_audio() and stt_capture.capture_transcript()
    require no changes.
    """

    def __init__(self, pipeline_str: str, read_fd: int, write_fd: int) -> None:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        self._write_fd = write_fd
        self._dead = False
        self._lock = threading.Lock()

        self.stdout = os.fdopen(read_fd, "rb", buffering=0)

        logger.info("GStreamer pipeline: %s", pipeline_str)
        self._pipeline = Gst.parse_launch(pipeline_str)
        self._bus = self._pipeline.get_bus()

        ret = self._pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            self._close_write_fd()
            raise RuntimeError("GStreamer pipeline failed to start PLAYING")

        self._bus_thread = threading.Thread(
            target=self._bus_watch, daemon=True, name="gst-bus-watch"
        )
        self._bus_thread.start()

    def _bus_watch(self) -> None:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        while True:
            with self._lock:
                if self._dead:
                    return
            msg = self._bus.timed_pop_filtered(
                100 * Gst.MSECOND,
                Gst.MessageType.ERROR | Gst.MessageType.EOS,
            )
            if msg is None:
                continue
            if msg.type == Gst.MessageType.ERROR:
                err, debug = msg.parse_error()
                logger.error("GStreamer ERROR: %s — %s", err, debug)
            else:
                logger.debug("GStreamer EOS")
            with self._lock:
                self._dead = True
            self._close_write_fd()
            return

    def _close_write_fd(self) -> None:
        try:
            os.close(self._write_fd)
        except OSError:
            pass

    def poll(self) -> int | None:
        with self._lock:
            return 1 if self._dead else None

    def terminate(self) -> None:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        with self._lock:
            self._dead = True
        self._pipeline.set_state(Gst.State.NULL)
        self._close_write_fd()

    def wait(self, timeout: float | None = None) -> int:
        self._bus_thread.join(timeout=timeout)
        return 1


def start_capture_gst(source_name: str | None, config) -> GStreamerCapture:
    """Start a GStreamer capture pipeline and return a GStreamerCapture handle."""
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        if not Gst.is_initialized():
            Gst.init(None)
    except ImportError as e:
        raise RuntimeError(
            "GStreamer Python bindings (PyGObject / gi) not installed. "
            "Install python3-gst-1.0 or the [gstreamer] optional dep."
        ) from e

    logger.info(
        "GStreamer capture: source=%s device=%s"
        " ns=%s(level=%d) agc=%s(target=%ddBFS gain=%ddB) hpf=%s compressor=%s",
        config.source,
        source_name or "default",
        config.noise_suppression,
        config.noise_suppression_level,
        config.agc,
        config.agc_target_level_dbfs,
        config.agc_compression_gain_db,
        config.high_pass_filter,
        config.compressor,
    )

    read_fd, write_fd = os.pipe()
    pipeline_str = _build_pipeline_string(source_name, config, write_fd)

    try:
        return GStreamerCapture(pipeline_str, read_fd, write_fd)
    except Exception:
        try:
            os.close(read_fd)
        except OSError:
            pass
        try:
            os.close(write_fd)
        except OSError:
            pass
        raise
