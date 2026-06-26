"""GStreamer-based audio capture backend for the STT pipeline.

Provides two capture paths:

* **pulsesrc** (default, ``audio.gstreamer.source: pulsesrc``): Python GI
  bindings drive a GStreamer pipeline with pulsesrc.  Works for devices whose
  PipeWire nodes appear under *Sources/Sinks* (e.g. NewPie with the combined
  analog-stereo+input profile).  Returns ``GStreamerCapture``.

* **pipewiresrc** (``audio.gstreamer.source: pipewiresrc``): spawns
  ``gst-launch-1.0`` as a subprocess.  The child process runs its own GLib
  main loop so pipewiresrc works correctly — without it pipewiresrc stalls
  after the first buffer.  Required for devices whose nodes appear under
  *Filters* (e.g. Yealink SP92 on the pro-audio profile).  Returns a plain
  ``subprocess.Popen`` whose stdout is raw s16le 16 kHz mono PCM.

Usage: selected via ``stt.capture_backend: gstreamer`` in config.yaml.
The active named profile (from ``audio.gstreamer.profiles``) can override
the ``source`` field to switch paths per device.
"""

from __future__ import annotations

import logging
import os
import subprocess
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

    cheblimit_stage = ""
    if getattr(config, "highpass_cutoff_hz", 0) > 0:
        cutoff = int(config.highpass_cutoff_hz)
        # audiocheblimit requires F32LE; audioconvert before it converts S16LE→F32LE.
        # The trailing audioconvert converts back to S16LE before webrtcdsp.
        cheblimit_stage = (
            f" ! audioconvert ! audiocheblimit mode=high-pass cutoff={cutoff} poles=4"
        )

    use_webrtcdsp = (
        config.noise_suppression or config.agc or config.high_pass_filter
    )
    webrtcdsp_stage = f" ! webrtcdsp {webrtc_props}" if use_webrtcdsp else ""

    return (
        f"{src_element}{device_prop}{latency}"
        f"{native_caps}"
        " ! audioconvert"
        " ! audioresample"
        " ! audio/x-raw,format=S16LE,rate=16000,channels=1"
        f"{cheblimit_stage}"
        " ! audioconvert"
        " ! audio/x-raw,format=S16LE,rate=16000,channels=1"
        f"{webrtcdsp_stage}"
        f"{compressor_stage}"
        " ! audioconvert"
        " ! audio/x-raw,format=S16LE,rate=16000,channels=1"
        " ! queue max-size-buffers=100 leaky=downstream"
        f" ! fdsink fd={write_fd} sync=false"
    )


def _build_gst_launch_cmdline(source_name: str | None, config) -> str:
    """Build a gst-launch-1.0 command string for the pipewiresrc subprocess path.

    Quotes the target-object value so names with hyphens/dots are not
    mis-parsed by gst-launch's element-property parser.
    """
    target_prop = f' target-object="{source_name}"' if source_name else ""

    ns_level = max(0, min(3, config.noise_suppression_level))
    target_dbfs = max(0, min(31, abs(config.agc_target_level_dbfs)))
    compression_db = max(0, min(90, config.agc_compression_gain_db))

    use_webrtcdsp = config.noise_suppression or config.agc or config.high_pass_filter

    webrtcdsp_stage = ""
    if use_webrtcdsp:
        webrtcdsp_stage = (
            f" ! webrtcdsp"
            f" noise-suppression={str(config.noise_suppression).lower()}"
            f" noise-suppression-level={ns_level}"
            f" gain-control={str(config.agc).lower()}"
            f" target-level-dbfs={target_dbfs}"
            f" compression-gain-db={compression_db}"
            f" high-pass-filter={str(config.high_pass_filter).lower()}"
            " echo-cancel=false voice-detection=false"
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

    cheblimit_stage = ""
    if getattr(config, "highpass_cutoff_hz", 0) > 0:
        cutoff = int(config.highpass_cutoff_hz)
        # audiocheblimit requires F32LE; audioconvert before it converts S16LE→F32LE.
        # The main pipeline's trailing audioconvert converts back to S16LE.
        cheblimit_stage = (
            f" ! audioconvert ! audiocheblimit mode=high-pass cutoff={cutoff} poles=4"
        )

    pipeline = (
        f"pipewiresrc{target_prop}"
        " ! audioconvert ! audioresample"
        " ! audio/x-raw,format=S16LE,rate=16000,channels=1"
        f"{cheblimit_stage}"
        f"{webrtcdsp_stage}"
        f"{compressor_stage}"
        " ! audioconvert"
        " ! audio/x-raw,format=S16LE,rate=16000,channels=1"
        " ! queue max-size-buffers=100 leaky=downstream"
        " ! fdsink fd=1 sync=false"
    )
    return f"gst-launch-1.0 -q {pipeline}"


class GstLaunchCapture:
    """Thin named wrapper around subprocess.Popen for gst-launch captures.

    The name lets stt_gating identify this backend in log messages without
    inspecting the command line.  All Popen attributes are forwarded.
    """

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc
        self.stdout = proc.stdout

    @property
    def returncode(self):
        return self._proc.returncode

    def poll(self):
        return self._proc.poll()

    def terminate(self) -> None:
        self._proc.terminate()

    def wait(self, timeout=None):
        return self._proc.wait(timeout=timeout)


def _start_capture_gst_subprocess(source_name: str | None, config) -> GstLaunchCapture:
    """Spawn gst-launch-1.0 as a subprocess using pipewiresrc.

    gst-launch-1.0 runs its own GLib main loop, which is required for
    pipewiresrc to work — without it the element stalls after the first
    PipeWire buffer.  The subprocess stdout is raw s16le 16 kHz mono PCM,
    consumed by the STT pipeline exactly like parec output.

    Needed for devices whose PipeWire nodes sit under *Filters* rather than
    *Sources/Sinks* (e.g. Yealink SP92 on the pro-audio profile): pulsesrc
    connects to such nodes through the PulseAudio compat socket but the node
    never exits SUSPENDED, delivering only zeros.  pipewiresrc targets the
    Filter node directly and receives real audio.
    """
    import shutil

    if not shutil.which("gst-launch-1.0"):
        raise RuntimeError(
            "gst-launch-1.0 not found — install gstreamer1.0-tools"
        )

    cmd = _build_gst_launch_cmdline(source_name, config)
    logger.info("GStreamer subprocess: %s", cmd)

    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    return GstLaunchCapture(proc)


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


def start_capture_gst(source_name: str | None, config):
    """Start a GStreamer capture pipeline.

    When ``config.source == "pipewiresrc"``, spawns ``gst-launch-1.0`` as a
    subprocess so pipewiresrc can use its own GLib main loop — required for
    devices whose PipeWire nodes appear under *Filters* (e.g. Yealink SP92 on
    the pro-audio profile).  Returns ``GstLaunchCapture``.

    Otherwise (``pulsesrc``) uses Python GI bindings and returns
    ``GStreamerCapture``.
    """
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

    if config.source == "pipewiresrc":
        return _start_capture_gst_subprocess(source_name, config)

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
