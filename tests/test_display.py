from __future__ import annotations

import logging
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from alexa_custom.config import DisplayConfig
from alexa_custom.display import (
    DisplayController,
    GpioLedDisplay,
    MockDisplay,
    STATE_COLORS,
    get_display_backend,
)


# ── MockDisplay ────────────────────────────────────────────────────────


class TestMockDisplay:
    def test_show_logs_state(self, caplog):
        caplog.set_level(logging.INFO)
        d = MockDisplay()
        d.show("listening")
        assert "listening" in caplog.text
        assert "display" in caplog.text

    def test_clear_logs(self, caplog):
        caplog.set_level(logging.INFO)
        d = MockDisplay()
        d.clear()
        assert "clear" in caplog.text

    def test_unknown_state_does_not_crash(self):
        d = MockDisplay()
        d.show("nonexistent_state")


# ── GpioLedDisplay (sysfs mock) ────────────────────────────────────────


class TestGpioLedDisplay:
    def test_show_writes_sysfs(self, tmp_path):
        d = GpioLedDisplay()
        d._led_base = str(tmp_path)
        for color in ("red", "green", "blue"):
            p = tmp_path / f"{color}:user" / "brightness"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("0")

        d.show("idle")
        assert (tmp_path / "blue:user" / "brightness").read_text().strip() == "1"
        assert (tmp_path / "red:user" / "brightness").read_text().strip() == "0"

    def test_clear_turns_all_off(self, tmp_path):
        d = GpioLedDisplay()
        d._led_base = str(tmp_path)
        for color in ("red", "green", "blue"):
            p = tmp_path / f"{color}:user" / "brightness"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("1")

        d.clear()
        for color in ("red", "green", "blue"):
            val = (tmp_path / f"{color}:user" / "brightness").read_text().strip()
            assert val == "0", f"{color} should be 0, got {val}"

    def test_missing_sysfs_does_not_crash(self):
        d = GpioLedDisplay()
        d._led_base = "/nonexistent"
        d.show("idle")
        d.clear()


# ── Factory ────────────────────────────────────────────────────────────


class TestGetDisplayBackend:
    def test_mock_explicit(self):
        backend = get_display_backend("mock")
        assert isinstance(backend, MockDisplay)

    def test_auto_falls_back_to_mock_when_no_hardware(self):
        backend = get_display_backend("auto")
        assert isinstance(backend, MockDisplay)

    def test_gpio_explicit_returns_mock(self):
        backend = get_display_backend("gpio")
        assert isinstance(backend, MockDisplay)

    def test_bridge_explicit_returns_mock(self):
        backend = get_display_backend("bridge")
        assert isinstance(backend, MockDisplay)


# ── DisplayController event mapping ────────────────────────────────────


class TestDisplayControllerEventMapping:
    def _make_controller(self) -> DisplayController:
        backend = MockDisplay()
        ctrl = DisplayController(backend)
        return ctrl

    def test_stt_wake_maps_to_wake(self):
        backend = MockDisplay()
        ctrl = DisplayController(backend)
        ctrl.on_stt_event("wake", {})
        time.sleep(0.1)
        ctrl.stop()

    def test_stt_listening_maps_to_wake(self):
        backend = MockDisplay()
        ctrl = DisplayController(backend)
        ctrl.on_stt_event("listening", {"wake_words": ["galileo"]})
        time.sleep(0.1)
        ctrl.stop()

    def test_stt_llm_thinking_maps(self):
        backend = MockDisplay()
        ctrl = DisplayController(backend)
        ctrl.on_stt_event("llm_thinking", {})
        time.sleep(0.1)
        ctrl.stop()

    def test_stt_level_is_ignored(self):
        backend = MagicMock()
        ctrl = DisplayController(backend)
        backend.show.reset_mock()
        ctrl.on_stt_event("level", {"mic": 0.5})
        time.sleep(0.1)
        ctrl.stop()
        backend.show.assert_not_called()

    def test_event_starting(self):
        backend = MockDisplay()
        ctrl = DisplayController(backend)
        ctrl.on_event("starting", {})
        time.sleep(0.1)
        ctrl.stop()

    def test_event_connected(self):
        backend = MockDisplay()
        ctrl = DisplayController(backend)
        ctrl.on_event("connected", {})
        time.sleep(0.1)
        ctrl.stop()

    def test_event_disconnected(self):
        backend = MockDisplay()
        ctrl = DisplayController(backend)
        ctrl.on_event("disconnected", {})
        time.sleep(0.1)
        ctrl.stop()

    def test_event_idle_returns_to_idle(self):
        backend = MockDisplay()
        ctrl = DisplayController(backend)
        ctrl.on_event("connected", {})
        ctrl.on_stt_event("wake", {})
        ctrl.on_event("disconnected", {})
        time.sleep(0.1)
        ctrl.stop()


# ── Config parsing ─────────────────────────────────────────────────────


class TestDisplayConfigParsing:
    def test_display_section_absent_returns_none(self, tmp_path):
        from alexa_custom.config import load_config
        from pathlib import Path

        conf_dir = tmp_path / "conf"
        conf_dir.mkdir()
        (conf_dir / "actions").mkdir()

        cfg_path = conf_dir / "config.yaml"
        cfg_path.write_text("wake_words:\n  - word: test\n")

        original_cwd = Path.cwd()
        try:
            import os
            os.chdir(str(tmp_path))
            config = load_config("conf/config.yaml")
        finally:
            os.chdir(str(original_cwd))

        assert config is not None
        assert config.display is None

    def test_display_section_present_parses_correctly(self, tmp_path):
        from alexa_custom.config import load_config
        from pathlib import Path

        conf_dir = tmp_path / "conf"
        conf_dir.mkdir()
        (conf_dir / "actions").mkdir()

        cfg_path = conf_dir / "config.yaml"
        cfg_path.write_text(
            "wake_words:\n  - word: test\n"
            "display:\n  enabled: true\n  backend: mock\n"
            "  matrix_brightness: 75\n"
        )

        original_cwd = Path.cwd()
        try:
            import os
            os.chdir(str(tmp_path))
            config = load_config("conf/config.yaml")
        finally:
            os.chdir(str(original_cwd))

        assert config is not None
        assert config.display is not None
        assert config.display.enabled is True
        assert config.display.backend == "mock"
        assert config.display.matrix_brightness == 75

    def test_display_section_disabled(self, tmp_path):
        from alexa_custom.config import load_config
        from pathlib import Path

        conf_dir = tmp_path / "conf"
        conf_dir.mkdir()
        (conf_dir / "actions").mkdir()

        cfg_path = conf_dir / "config.yaml"
        cfg_path.write_text(
            "wake_words:\n  - word: test\n"
            "display:\n  enabled: false\n"
        )

        original_cwd = Path.cwd()
        try:
            import os
            os.chdir(str(tmp_path))
            config = load_config("conf/config.yaml")
        finally:
            os.chdir(str(original_cwd))

        assert config is not None
        assert config.display is not None
        assert config.display.enabled is False


# ── State color map completeness ───────────────────────────────────────


class TestStateColors:
    def test_all_states_have_colors(self):
        expected_states = [
            "idle", "listening", "wake", "transcribing",
            "llm_thinking", "llm_reply", "speaking", "gated",
            "nomatch", "connected", "disconnected", "starting",
        ]
        for s in expected_states:
            assert s in STATE_COLORS, f"Missing color for {s}"
            assert len(STATE_COLORS[s]) == 3
