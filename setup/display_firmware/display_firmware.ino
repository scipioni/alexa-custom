/*
 * display_firmware.ino — Arduino UNO Q STM32U585 visual feedback
 *
 * Exposes RPC functions via Arduino_RouterBridge so the MPU (Linux/Python)
 * can control the 8x13 LED matrix and the two MCU-controlled RGB LEDs.
 *
 * Frame format: uint32_t[4], each uint32_t holds two rows:
 *   frame[i] = (row_{2i} << 16) | row_{2i+1}
 * Each row is a 13-bit mask (bit 0 = column 0, bit 12 = column 12).
 */

#include "Arduino_LED_Matrix.h"
#include "Arduino_RouterBridge.h"

ArduinoLEDMatrix matrix;

// ── 8×13 icon library ─────────────────────────────────────────────────
// Each icon is 4 × uint32_t. Use ROW(a,b) to pack two 13-bit rows into one word.

#define ROW(a, b) (((uint32_t)(a) << 16) | (uint32_t)(b))

// ICON_IDLE (0): filled rectangle centre
static const uint32_t ICON_IDLE[4] PROGMEM = {
  ROW(0b0000000000000, 0b0001111000000),
  ROW(0b0011111100000, 0b0111111110000),
  ROW(0b0111111110000, 0b0011111100000),
  ROW(0b0001111000000, 0b0000000000000),
};

// ICON_LISTEN (1): microphone
static const uint32_t ICON_LISTEN[4] PROGMEM = {
  ROW(0b0000110000000, 0b0001111000000),
  ROW(0b0001111000000, 0b0001111000000),
  ROW(0b0001111000000, 0b0001111000000),
  ROW(0b0000110000000, 0b0001111000000),
};

// ICON_TRANSCRIBE (2): vertical bars
static const uint32_t ICON_TRANSCRIBE[4] PROGMEM = {
  ROW(0b0010001000100, 0b0010001000100),
  ROW(0b0111011101110, 0b0111011101110),
  ROW(0b0010001000100, 0b0010001000100),
  ROW(0b0000000000000, 0b0000000000000),
};

// ICON_THINK (3): right arrow
static const uint32_t ICON_THINK[4] PROGMEM = {
  ROW(0b0000100000000, 0b0001100000000),
  ROW(0b0011111111110, 0b0011111111110),
  ROW(0b0001100000000, 0b0000100000000),
  ROW(0b0000000000000, 0b0000000000000),
};

// ICON_SPEAK (4): sound waves
static const uint32_t ICON_SPEAK[4] PROGMEM = {
  ROW(0b0001000000000, 0b0011000100000),
  ROW(0b0111001010000, 0b0111001010000),
  ROW(0b0011000100000, 0b0001000000000),
  ROW(0b0000000000000, 0b0000000000000),
};

// ICON_CALL (5): phone handset
static const uint32_t ICON_CALL[4] PROGMEM = {
  ROW(0b0111111111110, 0b0100000000010),
  ROW(0b0101111111010, 0b0100000000010),
  ROW(0b0111111111110, 0b0000000000000),
  ROW(0b0000000000000, 0b0000000000000),
};

// ICON_ERROR (6): X mark
static const uint32_t ICON_ERROR[4] PROGMEM = {
  ROW(0b1000000000001, 0b0100000000010),
  ROW(0b0010000000100, 0b0001000001000),
  ROW(0b0000100010000, 0b0000010100000),
  ROW(0b0000001000000, 0b0000000000000),
};

// ICON_CONNECT (7): Wi‑Fi arc
static const uint32_t ICON_CONNECT[4] PROGMEM = {
  ROW(0b0000000000000, 0b0111111111110),
  ROW(0b1000000000001, 0b0000000000000),
  ROW(0b0001111111000, 0b0000000000000),
  ROW(0b0000111110000, 0b0000000000000),
};

// ICON_OFF (8): all off
static const uint32_t ICON_OFF[4] PROGMEM = {
  ROW(0b0000000000000, 0b0000000000000),
  ROW(0b0000000000000, 0b0000000000000),
  ROW(0b0000000000000, 0b0000000000000),
  ROW(0b0000000000000, 0b0000000000000),
};

static const uint32_t *ICONS[] = {
  ICON_IDLE, ICON_LISTEN, ICON_TRANSCRIBE, ICON_THINK,
  ICON_SPEAK, ICON_CALL, ICON_ERROR, ICON_CONNECT, ICON_OFF,
};
static const uint8_t ICON_COUNT = sizeof(ICONS) / sizeof(ICONS[0]);

// ── MCU RGB LED pins (active LOW on UNO Q) ──────────────────────────
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

// ── RPC functions ───────────────────────────────────────────────────

void rpc_ping() {}

void rpc_set_matrix_icon(uint8_t icon_id) {
  if (icon_id >= ICON_COUNT) icon_id = ICON_COUNT - 1;
  matrix.loadFrame(ICONS[icon_id]);
}

void rpc_set_leds(uint8_t r, uint8_t g, uint8_t b,
                   uint8_t r1, uint8_t g1, uint8_t b1) {
  _set_mcu_led(LED0_R, LED0_G, LED0_B, r, g, b);
  _set_mcu_led(LED1_R, LED1_G, LED1_B, r1, g1, b1);
}

void rpc_clear() {
  matrix.loadFrame(ICON_OFF);
  _set_both_leds(0, 0, 0);
}

// ── Setup ───────────────────────────────────────────────────────────

void setup() {
  for (auto pin : {LED0_R, LED0_G, LED0_B, LED1_R, LED1_G, LED1_B}) {
    pinMode(pin, OUTPUT);
    analogWrite(pin, 255);
  }

  matrix.begin();

  Bridge.provide("ping", rpc_ping);
  Bridge.provide("set_matrix_icon", rpc_set_matrix_icon);
  Bridge.provide("set_leds", rpc_set_leds);
  Bridge.provide("clear", rpc_clear);

  _set_both_leds(0, 0, 255);
  delay(200);
  _set_both_leds(0, 0, 0);
  delay(100);
  matrix.loadFrame(ICON_IDLE);
}

void loop() {
  delay(100);
}
