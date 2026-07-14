"""Tests for the shared DSP stage builder (harden-serena-runtime task 6.1):
the gst-launch-1.0 subprocess pipeline must link audiocheblimit's F32LE
output back to S16LE via audioconvert before webrtcdsp, exactly like the
in-process pipeline. Missing this breaks pipeline linking for the
SP92-direct config (pipewiresrc + highpass_cutoff_hz > 0)."""

from alexa_custom.config import GStreamerCaptureConfig
from alexa_custom.stt_gst_capture import (
    _build_gst_launch_cmdline,
    _build_pipeline_string,
)


def test_gst_launch_cmdline_converts_back_to_s16le_after_highpass():
    cfg = GStreamerCaptureConfig(
        source="pipewiresrc", highpass_cutoff_hz=220, agc=True, noise_suppression=False
    )
    cmd = _build_gst_launch_cmdline("test_source", cfg)

    assert "audiocheblimit mode=high-pass cutoff=220" in cmd
    # The cheblimit stage must be followed by an audioconvert back to S16LE
    # before webrtcdsp — not directly by webrtcdsp on F32LE output.
    highpass_idx = cmd.index("audiocheblimit")
    after_highpass = cmd[highpass_idx:]
    assert after_highpass.index("audioconvert") < after_highpass.index("webrtcdsp")


def test_pipeline_string_converts_back_to_s16le_after_highpass():
    cfg = GStreamerCaptureConfig(
        source="pulsesrc", highpass_cutoff_hz=220, agc=True, noise_suppression=False
    )
    pipeline = _build_pipeline_string("test_source", cfg, write_fd=5)

    highpass_idx = pipeline.index("audiocheblimit")
    after_highpass = pipeline[highpass_idx:]
    assert after_highpass.index("audioconvert") < after_highpass.index("webrtcdsp")


def test_no_highpass_omits_cheblimit_in_both_builders():
    cfg = GStreamerCaptureConfig(highpass_cutoff_hz=0)
    assert "audiocheblimit" not in _build_gst_launch_cmdline("src", cfg)
    assert "audiocheblimit" not in _build_pipeline_string("src", cfg, write_fd=5)


def test_dsp_stage_order_matches_between_builders():
    """Both builders must produce the same DSP element ordering for the
    same config, since they now share _build_dsp_stages."""
    cfg = GStreamerCaptureConfig(
        highpass_cutoff_hz=220,
        agc=True,
        noise_suppression=True,
        compressor=True,
        expander=True,
    )
    launch_cmd = _build_gst_launch_cmdline("src", cfg)
    pipeline_str = _build_pipeline_string("src", cfg, write_fd=5)

    elements = [
        "audiocheblimit",
        "webrtcdsp",
        "audiodynamic mode=compressor",
        "audiodynamic mode=expander",
    ]
    launch_positions = [launch_cmd.index(e) for e in elements]
    pipeline_positions = [pipeline_str.index(e) for e in elements]
    assert launch_positions == sorted(launch_positions)
    assert pipeline_positions == sorted(pipeline_positions)
