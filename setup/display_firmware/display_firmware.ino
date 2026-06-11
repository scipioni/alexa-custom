/*
 * display_firmware.ino — Arduino UNO Q STM32U585 visual feedback
 *
 * Exposes RPC functions via ArduinoRouterBridge so the MPU (Linux/Python)
 * can control the 8x13 LED matrix and the two MCU-controlled RGB LEDs.
 *
 * Flash this sketch onto the UNO Q via USB once, then alexa-custom
 * will drive the display through Bridge.call().
 *
 * Icon format (column-major):
 *   uint8_t frame[13] — each byte is one column (8 pixels, MSB = top row).
 */

#include "Arduino_LED_Matrix.h"
#include "ArduinoRouterBridge.h"

ArduinoLEDMatrix matrix;

// ── 8×13 column-major bitmaps ──────────────────────────────────────────
// Each icon is 13 bytes, one per column; bit 7 = top row, bit 0 = bottom row.

// ICON_IDLE (0): small circle centre
static const uint8_t ICON_IDLE[13] PROGMEM = {
  0x00, 0x00, 0x3C, 0x42, 0x81, 0x81, 0x81, 0x81, 0x42, 0x3C, 0x00, 0x00, 0x00
};

// ICON_LISTEN (1): microphone outline
static const uint8_t ICON_LISTEN[13] PROGMEM = {
  0x00, 0x00, 0x18, 0x24, 0x42, 0x42, 0x42, 0x42, 0x66, 0x3C, 0x18, 0x00, 0x00
};

// ICON_TRANSCRIBE (2): equaliser bars
static const uint8_t ICON_TRANSCRIBE[13] PROGMEM = {
  0x00, 0x00, 0x00, 0x24, 0x24, 0x24, 0xFF, 0x24, 0x24, 0x24, 0x00, 0x00, 0x00
};

// ICON_THINK (3): right arrow (spinner frame 1)
static const uint8_t ICON_THINK[13] PROGMEM = {
  0x00, 0x00, 0x10, 0x18, 0x1C, 0x1E, 0xFF, 0x1E, 0x1C, 0x18, 0x10, 0x00, 0x00
};

// ICON_SPEAK (4): sound waves
static const uint8_t ICON_SPEAK[13] PROGMEM = {
  0x00, 0x00, 0x18, 0x14, 0x22, 0x49, 0x09, 0x49, 0x22, 0x14, 0x18, 0x00, 0x00
};

// ICON_CALL (5): telephone handset
static const uint8_t ICON_CALL[13] PROGMEM = {
  0x00, 0x00, 0xFE, 0x82, 0xBA, 0x82, 0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};

// ICON_ERROR (6): X mark
static const uint8_t ICON_ERROR[13] PROGMEM = {
  0x00, 0x00, 0x81, 0x42, 0x24, 0x18, 0x18, 0x24, 0x42, 0x81, 0x00, 0x00, 0x00
};

// ICON_CONNECT (7): Wi‑Fi arc
static const uint8_t ICON_CONNECT[13] PROGMEM = {
  0x00, 0x00, 0x00, 0x7E, 0x81, 0x00, 0x3C, 0x00, 0x18, 0x00, 0x00, 0x00, 0x00
};

// ICON_OFF (8): all off
static const uint8_t ICON_OFF[13] PROGMEM = {
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};

static const uint8_t *ICONS[] = {
  ICON_IDLE,
  ICON_LISTEN,
  ICON_TRANSCRIBE,
  ICON_THINK,
  ICON_SPEAK,
  ICON_CALL,
  ICON_ERROR,
  ICON_CONNECT,
  ICON_OFF,
};
static const uint8_t ICON_COUNT = sizeof(ICONS) / sizeof(ICONS[0]);

// ── MCU RGB LED pins (GPIO, active LOW on UNO Q) ──────────────────────
// Adjust pin numbers to match your board's schematic.
static const uint8_t LED0_R = 6;
static const uint8_t LED0_G = 5;
static const uint8_t LED0_B = 3;
static const uint8_t LED1_R = 9;
static const uint8_t LED1_G = 10;
static const uint8_t LED1_B = 11;

void _set_mcu_led(uint8_t r_pin, uint8_t g_pin, uint8_t b_pin,
                   uint8_t r, uint8_t g, uint8_t b) {
  analogWrite(r_pin, 255 - r);
  analogWrite(g_pin, 255 - g);
  analogWrite(b_pin, 255 - b);
}

void _set_both_leds(uint8_t r, uint8_t g, uint8_t b) {
  _set_mcu_led(LED0_R, LED0_G, LED0_B, r, g, b);
  _set_mcu_led(LED1_R, LED1_G, LED1_B, r, g, b);
}

// ── RPC functions (called by Python via Bridge.call) ───────────────────

void rpc_ping() {
  // No-op; the Bridge confirms the function exists.
}

void rpc_set_matrix_icon(uint8_t icon_id) {
  if (icon_id >= ICON_COUNT) icon_id = ICON_COUNT - 1;
  matrix.loadFrame(ICONS[icon_id]);
  matrix.write();
}

void rpc_set_leds(uint8_t r, uint8_t g, uint8_t b,
                   uint8_t r1, uint8_t g1, uint8_t b1) {
  _set_mcu_led(LED0_R, LED0_G, LED0_B, r, g, b);
  _set_mcu_led(LED1_R, LED1_G, LED1_B, r1, g1, b1);
}

void rpc_clear() {
  matrix.clear();
  matrix.write();
  _set_both_leds(0, 0, 0);
}

// ── Setup ─────────────────────────────────────────────────────────────

void setup() {
  for (auto pin : {LED0_R, LED0_G, LED0_B, LED1_R, LED1_G, LED1_B}) {
    pinMode(pin, OUTPUT);
    analogWrite(pin, 255);  // off (active LOW)
  }

  matrix.begin();

  Bridge.provide("ping", rpc_ping);
  Bridge.provide("set_matrix_icon", rpc_set_matrix_icon);
  Bridge.provide("set_leds", rpc_set_leds);
  Bridge.provide("clear", rpc_clear);

  // Boot animation: flash LEDs then show idle icon
  _set_both_leds(0, 0, 255);
  delay(200);
  _set_both_leds(0, 0, 0);
  delay(100);
  matrix.loadFrame(ICON_IDLE);
  matrix.write();
}

void loop() {
  // Event-driven — nothing to do here.
  delay(100);
}
