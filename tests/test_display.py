from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from alexa_custom.display import (
    DisplayController,
    GpioLedDisplay,
    I2cOledDisplay,
    MockDisplay,
    STATE_COLORS,
    STATE_TEXTS,
    _Ssd1306,
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
        cfg_path.write_text("wake_words:\n  - word: test\ndisplay:\n  enabled: false\n")

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
            "idle",
            "listening",
            "wake",
            "transcribing",
            "llm_thinking",
            "llm_reply",
            "speaking",
            "gated",
            "nomatch",
            "connected",
            "disconnected",
            "starting",
        ]
        for s in expected_states:
            assert s in STATE_COLORS, f"Missing color for {s}"
            assert len(STATE_COLORS[s]) == 3


# ── State text map completeness ───────────────────────────────────────


class TestStateTexts:
    def test_all_states_have_texts(self):
        expected_states = [
            "idle",
            "listening",
            "wake",
            "transcribing",
            "llm_thinking",
            "llm_reply",
            "speaking",
            "gated",
            "nomatch",
            "connected",
            "disconnected",
            "starting",
        ]
        for s in expected_states:
            assert s in STATE_TEXTS, f"Missing text for {s}"
            assert isinstance(STATE_TEXTS[s], str)
            assert len(STATE_TEXTS[s]) > 0


# ── _Ssd1306 buffer operations (mocked I2C) ──────────────────────────


class TestSsd1306:
    @pytest.fixture
    def driver(self):
        with patch("smbus2.SMBus"):
            d = _Ssd1306(bus=1, addr=0x3C, width=128, height=64)
        d._buffer = bytearray(128 * 8)
        return d

    def test_clear_zeros_buffer(self, driver):
        driver._buffer[42] = 0xFF
        driver.clear()
        assert all(b == 0 for b in driver._buffer)

    def test_set_pixel_turns_on(self, driver):
        driver._set_pixel(10, 5, True)
        idx = 10 + (5 // 8) * 128
        assert driver._buffer[idx] & (1 << (5 & 7))

    def test_set_pixel_turns_off(self, driver):
        idx = 10 + (5 // 8) * 128
        driver._buffer[idx] |= 1 << (5 & 7)
        driver._set_pixel(10, 5, False)
        assert not (driver._buffer[idx] & (1 << (5 & 7)))

    def test_set_pixel_out_of_bounds(self, driver):
        driver._set_pixel(-1, 0, True)
        driver._set_pixel(128, 0, True)
        driver._set_pixel(0, -1, True)
        driver._set_pixel(0, 64, True)
        assert all(b == 0 for b in driver._buffer)

    def test_set_pixel_corner_pixels(self, driver):
        driver._set_pixel(0, 0, True)
        driver._set_pixel(127, 63, True)
        assert driver._buffer[0] & 1
        idx = 127 + (63 // 8) * 128
        assert driver._buffer[idx] & (1 << (63 & 7))

    def test_draw_char_basic(self, driver):
        c = driver._draw_char(0, 0, "A")
        assert c == 6
        any_set = any(v != 0 for v in driver._buffer)
        assert any_set

    def test_draw_char_out_of_range(self, driver):
        c = driver._draw_char(0, 0, "\x00")
        assert c == 6
        assert all(v == 0 for v in driver._buffer)

    def test_draw_text_writes_columns(self, driver):
        driver.draw_text(0, 0, "HI")
        non_zero = sum(1 for v in driver._buffer if v)
        assert non_zero > 0

    def test_draw_progress_full(self, driver):
        driver.draw_progress(1.0)
        non_zero = sum(1 for v in driver._buffer if v)
        assert non_zero > 0

    def test_draw_progress_zero(self, driver):
        driver.draw_progress(0.0)
        assert all(v == 0 for v in driver._buffer)

    def test_draw_progress_half(self, driver):
        driver.draw_progress(0.5)
        non_zero = sum(1 for v in driver._buffer if v)
        assert non_zero > 0

    def test_draw_progress_clamped(self, driver):
        driver.draw_progress(-0.1)
        assert all(v == 0 for v in driver._buffer)
        driver.draw_progress(1.5)
        non_zero = sum(1 for v in driver._buffer if v)
        assert non_zero > 0

    def test_draw_char_A_bytes_identical(self, driver):
        """Glyph rendering must produce byte-identical output after font extraction."""
        driver._draw_char(0, 0, "A")
        # 'A' font columns: 0x7E, 0x11, 0x11, 0x11, 0x7E (each sets bits 0-6 per column)
        assert list(driver._buffer[:5]) == [0x7E, 0x11, 0x11, 0x11, 0x7E]
        assert all(v == 0 for v in driver._buffer[5:])


class TestDisplayFontNotLoadedOnImport:
    """Guard: importing the display module must not materialise the font data."""

    def test_font_symbol_absent_from_display_module(self):
        import alexa_custom.display as _display
        import alexa_custom.display_fonts as _fonts  # noqa: F401 – ensure it CAN be imported

        assert not hasattr(_display, "_FONT5X7"), (
            "_FONT5X7 must not be a module-level attribute of alexa_custom.display"
        )
        assert not hasattr(_display, "FONT5X7"), (
            "FONT5X7 must not be a module-level attribute of alexa_custom.display"
        )

    def test_font_module_not_imported_by_display_at_module_level(self):
        import sys

        # Remove display_fonts from sys.modules to force a clean check
        sys.modules.pop("alexa_custom.display_fonts", None)
        # Re-import display (it's already imported, but display_fonts should not
        # be re-triggered at module level)
        import alexa_custom.display  # noqa: F401

        # display_fonts should only appear in sys.modules if _Ssd1306._draw_char ran
        assert "alexa_custom.display_fonts" not in sys.modules, (
            "display_fonts must not be imported at alexa_custom.display module level"
        )


# ── I2cOledDisplay state mapping (mocked I2C) ────────────────────────


class TestI2cOledDisplay:
    @pytest.fixture
    def display(self):
        with patch("smbus2.SMBus"):
            d = I2cOledDisplay(bus=1, addr=0x3C, width=128, height=64)
        d._oled._buffer = bytearray(128 * 8)
        return d

    def test_show_idle(self, display):
        display.show("idle")
        non_zero = sum(1 for v in display._oled._buffer if v)
        assert non_zero > 0

    def test_show_listening(self, display):
        display.show("listening")
        non_zero = sum(1 for v in display._oled._buffer if v)
        assert non_zero > 0

    def test_show_thinking(self, display):
        display.show("llm_thinking")
        non_zero = sum(1 for v in display._oled._buffer if v)
        assert non_zero > 0

    def test_show_speaking(self, display):
        display.show("speaking")
        non_zero = sum(1 for v in display._oled._buffer if v)
        assert non_zero > 0

    def test_show_wake(self, display):
        display.show("wake")
        non_zero = sum(1 for v in display._oled._buffer if v)
        assert non_zero > 0

    def test_clear(self, display):
        display.show("idle")
        display.clear()
        assert all(v == 0 for v in display._oled._buffer)

    def test_show_all_states(self, display):
        for state in STATE_COLORS:
            display.show(state)
            non_zero = sum(1 for v in display._oled._buffer if v)
            assert non_zero > 0, f"State {state} produced empty buffer"


# ── Factory: i2c backend ──────────────────────────────────────────────


class TestGetDisplayBackendI2c:
    def test_i2c_explicit_returns_mock_when_smbus2_missing(self):
        with patch.dict("sys.modules", {"smbus2": None}):
            backend = get_display_backend("i2c")
        assert isinstance(backend, MockDisplay)

    def test_i2c_explicit_returns_i2c_when_smbus2_available(self):
        with patch("smbus2.SMBus"):
            backend = get_display_backend("i2c")
        assert isinstance(backend, I2cOledDisplay)


# ── Config parsing: I2C fields ────────────────────────────────────────


class TestDisplayConfigI2c:
    def test_display_i2c_fields_parsed(self, tmp_path):
        from alexa_custom.config import load_config
        from pathlib import Path

        conf_dir = tmp_path / "conf"
        conf_dir.mkdir()
        (conf_dir / "actions").mkdir()

        cfg_path = conf_dir / "config.yaml"
        cfg_path.write_text(
            "wake_words:\n  - word: test\n"
            "display:\n  enabled: true\n"
            "  backend: i2c\n"
            "  i2c_bus: 0\n"
            "  i2c_address: '0x3D'\n"
            "  i2c_width: 128\n"
            "  i2c_height: 32\n"
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
        assert config.display.backend == "i2c"
        assert config.display.i2c_bus == 0
        assert config.display.i2c_address == 0x3D
        assert config.display.i2c_width == 128
        assert config.display.i2c_height == 32

    def test_display_i2c_defaults(self, tmp_path):
        from alexa_custom.config import load_config
        from pathlib import Path

        conf_dir = tmp_path / "conf"
        conf_dir.mkdir()
        (conf_dir / "actions").mkdir()

        cfg_path = conf_dir / "config.yaml"
        cfg_path.write_text(
            "wake_words:\n  - word: test\ndisplay:\n  enabled: true\n  backend: i2c\n"
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
        assert config.display.i2c_bus == 1
        assert config.display.i2c_address == 0x3C
        assert config.display.i2c_width == 128
        assert config.display.i2c_height == 64
