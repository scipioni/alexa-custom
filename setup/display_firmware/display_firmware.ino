/*
 * display_firmware.ino — Arduino UNO Q STM32U585 visual feedback
 *
 * Standalone RPC server (no Router dependency). Communicates directly
 * over Serial1 using the Arduino_RPClite protocol.
 *
 * Frame format: uint32_t[4], each uint32_t holds two rows:
 *   frame[i] = (row_{2i} << 16) | row_{2i+1}
 * Each row is a 13-bit mask (bit 0 = column 0, bit 12 = column 12).
 */

#include "Arduino_LED_Matrix.h"
#include "Arduino_RPClite.h"

ArduinoLEDMatrix matrix;

// ── 8×13 icon library ─────────────────────────────────────────────────
#define ROW(a, b) (((uint32_t)(a) << 16) | (uint32_t)(b))

static const uint32_t ICON_IDLE[4] = {
  ROW(0b0000000000000, 0b0001111000000),
  ROW(0b0011111100000, 0b0111111110000),
  ROW(0b0111111110000, 0b0011111100000),
  ROW(0b0001111000000, 0b0000000000000),
};

static const uint32_t ICON_LISTEN[4] = {
  ROW(0b0000110000000, 0b0001111000000),
  ROW(0b0001111000000, 0b0001111000000),
  ROW(0b0001111000000, 0b0001111000000),
  ROW(0b0000110000000, 0b0001111000000),
};

static const uint32_t ICON_TRANSCRIBE[4] = {
  ROW(0b0010001000100, 0b0010001000100),
  ROW(0b0111011101110, 0b0111011101110),
  ROW(0b0010001000100, 0b0010001000100),
  ROW(0b0000000000000, 0b0000000000000),
};

static const uint32_t ICON_THINK[4] = {
  ROW(0b0000100000000, 0b0001100000000),
  ROW(0b0011111111110, 0b0011111111110),
  ROW(0b0001100000000, 0b0000100000000),
  ROW(0b0000000000000, 0b0000000000000),
};

static const uint32_t ICON_SPEAK[4] = {
  ROW(0b0001000000000, 0b0011000100000),
  ROW(0b0111001010000, 0b0111001010000),
  ROW(0b0011000100000, 0b0001000000000),
  ROW(0b0000000000000, 0b0000000000000),
};

static const uint32_t ICON_CALL[4] = {
  ROW(0b0111111111110, 0b0100000000010),
  ROW(0b0101111111010, 0b0100000000010),
  ROW(0b0111111111110, 0b0000000000000),
  ROW(0b0000000000000, 0b0000000000000),
};

static const uint32_t ICON_ERROR[4] = {
  ROW(0b1000000000001, 0b0100000000010),
  ROW(0b0010000000100, 0b0001000001000),
  ROW(0b0000100010000, 0b0000010100000),
  ROW(0b0000001000000, 0b0000000000000),
};

static const uint32_t ICON_CONNECT[4] = {
  ROW(0b0000000000000, 0b0111111111110),
  ROW(0b1000000000001, 0b0000000000000),
  ROW(0b0001111111000, 0b0000000000000),
  ROW(0b0000111110000, 0b0000000000000),
};

static const uint32_t ICON_OFF[4] = { 0, 0, 0, 0 };

static const uint32_t *ICONS[] = {
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

// ── RPC functions (bound directly to RPCServer) ─────────────────────

bool rpc_ping() {
  return true;
}

void rpc_set_matrix_icon(uint8_t icon_id) {
  if (icon_id >= ICON_COUNT) icon_id = ICON_COUNT - 1;
  matrix.loadFrame(ICONS[icon_id]);
}

void rpc_set_leds(uint8_t r, uint8_t g, uint8_t b,
                  uint8_t r1, uint8_t g1, uint8_t b1) {
  _set_led(LED_PINS[0], LED_PINS[1], LED_PINS[2], r, g, b);
  _set_led(LED_PINS[3], LED_PINS[4], LED_PINS[5], r1, g1, b1);
}

void rpc_clear() {
  matrix.loadFrame(ICON_OFF);
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
  matrix.loadFrame(ICON_IDLE);
}

void loop() {
  rpc_server.run();
  delay(10);
}
