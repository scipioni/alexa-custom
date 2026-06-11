/*
 * display_firmware.ino — Arduino UNO Q STM32U585 visual feedback
 *
 * Standalone RPC server (no Router dependency). Communicates directly
 * over Serial1 using the Arduino_RPClite protocol.
 *
 * Icons are defined as row-major byte arrays (8 rows × 13 cols = 104 bytes).
 * Each byte is 0 (off) or 1 (on).
 */

#include "Arduino_LED_Matrix.h"
#include "Arduino_RPClite.h"

ArduinoLEDMatrix matrix;

// ── 8×13 row-major icons (104 bytes each: 13 cols × 8 rows) ─────────

// ICON_IDLE (0): filled rectangle centre
static const uint8_t ICON_IDLE[104] = {
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,1,1,1,1,0,0,0,0,0,
  0,0,0,1,1,1,1,1,1,0,0,0,0,
  0,0,1,1,1,1,1,1,1,1,0,0,0,
  0,0,1,1,1,1,1,1,1,1,0,0,0,
  0,0,0,1,1,1,1,1,1,0,0,0,0,
  0,0,0,0,1,1,1,1,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
};

// ICON_LISTEN (1): microphone
static const uint8_t ICON_LISTEN[104] = {
  0,0,0,0,0,1,1,0,0,0,0,0,0,
  0,0,0,0,1,1,1,1,0,0,0,0,0,
  0,0,0,0,1,1,1,1,0,0,0,0,0,
  0,0,0,0,1,1,1,1,0,0,0,0,0,
  0,0,0,0,1,1,1,1,0,0,0,0,0,
  0,0,0,0,0,1,1,0,0,0,0,0,0,
  0,0,0,0,0,1,1,0,0,0,0,0,0,
  0,0,0,0,1,1,1,1,0,0,0,0,0,
};

// ICON_TRANSCRIBE (2): equaliser bars
static const uint8_t ICON_TRANSCRIBE[104] = {
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,1,0,0,0,1,0,0,0,1,0,0,
  0,0,1,0,0,0,1,0,0,0,1,0,0,
  0,0,1,1,1,0,1,1,1,0,1,1,1,
  0,0,1,1,1,0,1,1,1,0,1,1,1,
  0,0,1,0,0,0,1,0,0,0,1,0,0,
  0,0,1,0,0,0,1,0,0,0,1,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
};

// ICON_THINK (3): right arrow
static const uint8_t ICON_THINK[104] = {
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,1,0,0,0,0,0,0,0,
  0,0,0,0,0,1,1,0,0,0,0,0,0,
  0,0,0,1,1,1,1,1,1,1,1,1,0,
  0,0,0,1,1,1,1,1,1,1,1,1,0,
  0,0,0,0,0,1,1,0,0,0,0,0,0,
  0,0,0,0,0,1,0,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
};

// ICON_SPEAK (4): sound waves
static const uint8_t ICON_SPEAK[104] = {
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,1,0,0,0,0,0,0,0,0,
  0,0,0,1,1,0,0,0,1,0,0,0,0,
  0,0,1,1,1,0,0,1,0,1,0,0,0,
  0,0,1,1,1,0,0,1,0,1,0,0,0,
  0,0,0,1,1,0,0,0,1,0,0,0,0,
  0,0,0,0,1,0,0,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
};

// ICON_CALL (5): phone handset
static const uint8_t ICON_CALL[104] = {
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,1,1,1,1,1,1,1,1,1,1,0,
  0,0,1,0,0,0,0,0,0,0,0,1,0,
  0,0,1,0,1,1,1,1,1,0,0,1,0,
  0,0,1,0,0,0,0,0,0,0,0,1,0,
  0,0,1,1,1,1,1,1,1,1,1,1,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
};

// ICON_ERROR (6): X mark
static const uint8_t ICON_ERROR[104] = {
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,1,1,0,0,0,0,0,0,
  0,0,0,0,0,1,1,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
};

// ICON_CONNECT (7): Wi‑Fi arc (simple bar)
static const uint8_t ICON_CONNECT[104] = {
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,1,1,1,1,1,0,0,0,0,
  0,0,0,1,0,0,0,0,0,1,0,0,0,
  0,0,0,0,0,1,1,1,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,1,1,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
};

// ICON_OFF (8): all off
static const uint8_t ICON_OFF[104] = {0};

static const uint8_t *ICONS[] = {
  ICON_IDLE, ICON_LISTEN, ICON_TRANSCRIBE, ICON_THINK,
  ICON_SPEAK, ICON_CALL, ICON_ERROR, ICON_CONNECT, ICON_OFF,
};
static const uint8_t ICON_COUNT = sizeof(ICONS) / sizeof(ICONS[0]);

// ── MCU RGB LED pins (active LOW on UNO Q) ──────────────────────────
static const uint8_t LED_PINS[] = { 6, 5, 3, 9, 10, 11 };

static void _set_led(uint8_t r_pin, uint8_t g_pin, uint8_t b_pin,
                     uint8_t r, uint8_t g, uint8_t b) {
  analogWrite(r_pin, 255 - r);
  analogWrite(g_pin, 255 - g);
  analogWrite(b_pin, 255 - b);
}

static void _set_both_leds(uint8_t r, uint8_t g, uint8_t b) {
  _set_led(LED_PINS[0], LED_PINS[1], LED_PINS[2], r, g, b);
  _set_led(LED_PINS[3], LED_PINS[4], LED_PINS[5], r, g, b);
}

// ── RPC functions ───────────────────────────────────────────────────

bool rpc_ping() {
  return true;
}

void rpc_set_matrix_icon(uint8_t icon_id) {
  if (icon_id >= ICON_COUNT) icon_id = ICON_COUNT - 1;
  matrix.loadPixels((uint8_t *)ICONS[icon_id], 104);
}

void rpc_set_leds(uint8_t r, uint8_t g, uint8_t b,
                  uint8_t r1, uint8_t g1, uint8_t b1) {
  _set_led(LED_PINS[0], LED_PINS[1], LED_PINS[2], r, g, b);
  _set_led(LED_PINS[3], LED_PINS[4], LED_PINS[5], r1, g1, b1);
}

void rpc_clear() {
  matrix.loadPixels((uint8_t *)ICON_OFF, 104);
  _set_both_leds(0, 0, 0);
}

// ── RPC transport & server ──────────────────────────────────────────

SerialTransport rpc_transport(Serial1);
RPCServer rpc_server(rpc_transport);

// ── Setup ───────────────────────────────────────────────────────────

void setup() {
  for (auto pin : LED_PINS) {
    pinMode(pin, OUTPUT);
    analogWrite(pin, 255);
  }

  matrix.begin();

  Serial1.begin(115200);
  while (!Serial1) {
    delay(10);
  }

  rpc_server.bind("ping", rpc_ping);
  rpc_server.bind("set_matrix_icon", rpc_set_matrix_icon);
  rpc_server.bind("set_leds", rpc_set_leds);
  rpc_server.bind("clear", rpc_clear);

  _set_both_leds(0, 0, 255);
  delay(200);
  _set_both_leds(0, 0, 0);
  delay(100);
  matrix.loadPixels((uint8_t *)ICON_IDLE, 104);
}

void loop() {
  rpc_server.run();
  delay(10);
}
