/*
 * display_firmware.ino — Arduino UNO Q STM32U585 visual feedback
 *
 * Uses the global Bridge object (RouterBridge) to register RPC methods
 * with the arduino-router on the MPU side. Text via ArduinoGraphics.
 * LEDs via analogWrite (active LOW).
 */

#include <Arduino_RouterBridge.h>
#include "ArduinoGraphics.h"
#include "Arduino_LED_Matrix.h"

ArduinoLEDMatrix matrix;

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

// ── Display helpers ─────────────────────────────────────────────────

static void _show_text(const char *text) {
  matrix.beginDraw();
  matrix.clear();
  int len = strlen(text);
  if (len <= 2) {
    matrix.textFont(Font_5x7);
    int x = (13 - len * 5) / 2;
    matrix.text(text, x < 0 ? 0 : x, 1);
  } else {
    matrix.textFont(Font_4x6);
    matrix.text(text, 0, 1);
  }
  matrix.endDraw();
}

static const uint8_t SYMBOL_OFF[104] = {0};

// ── RPC functions ───────────────────────────────────────────────────

bool rpc_ping() {
  return true;
}

void rpc_set_text(String text) {
  _show_text(text.c_str());
}

void rpc_set_leds(int r, int g, int b,
                  int r1, int g1, int b1) {
  _set_led(LED_PINS[0], LED_PINS[1], LED_PINS[2], r, g, b);
  _set_led(LED_PINS[3], LED_PINS[4], LED_PINS[5], r1, g1, b1);
}

void rpc_clear() {
  matrix.loadPixels((uint8_t *)SYMBOL_OFF, 104);
  _set_both_leds(0, 0, 0);
}

// ── Setup ───────────────────────────────────────────────────────────

void setup() {
  for (auto pin : LED_PINS) {
    pinMode(pin, OUTPUT);
    analogWrite(pin, 255);
  }

  matrix.begin();

  delay(1000);
  Bridge.begin();
  Monitor.begin();
  while (!Bridge) {
    delay(100);
  }

  Bridge.provide("ping", rpc_ping);
  Bridge.provide("set_text", rpc_set_text);
  Bridge.provide("set_leds", rpc_set_leds);
  Bridge.provide("clear", rpc_clear);

  _set_both_leds(0, 0, 255);
  delay(200);
  _set_both_leds(0, 0, 0);
  delay(100);
  _show_text("GO");
}

void loop() {
  __loopHook();
  delay(10);
}
