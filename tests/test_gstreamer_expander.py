import pytest
from alexa_custom.config import GStreamerCaptureConfig
from alexa_custom.stt_gst_capture import _build_gst_launch_cmdline

def test_gstreamer_capture_config_defaults():
    cfg = GStreamerCaptureConfig()
    assert cfg.expander is False
    assert cfg.expander_threshold == 0.05
    assert cfg.expander_ratio == 3.0

def test_gstreamer_pipeline_with_expander():
    cfg = GStreamerCaptureConfig(
        expander=True,
        expander_threshold=0.08,
        expander_ratio=4.0
    )
    cmd = _build_gst_launch_cmdline("test_source", cfg)
    # Verify that audiodynamic mode=expander is present in the pipeline command
    assert "audiodynamic mode=expander" in cmd
    assert "threshold=0.0800" in cmd
    assert "ratio=4.00" in cmd

def test_gstreamer_pipeline_without_expander():
    cfg = GStreamerCaptureConfig(expander=False)
    cmd = _build_gst_launch_cmdline("test_source", cfg)
    assert "audiodynamic mode=expander" not in cmd
