// SPDX-FileCopyrightText: Copyright (C) 2025 ARDUINO SA <http://www.arduino.cc>
//
// SPDX-License-Identifier: MPL-2.0
//
// RouterBridge RPC server for alexa-custom display feedback.
// Controls the built-in 8x13 LED matrix and STM32-side RGB LEDs (3 & 4).

#include <Arduino_RouterBridge.h>
#include "ArduinoGraphics.h"
#include "Arduino_LED_Matrix.h"

Arduino_LED_Matrix matrix;

// ── RPC providers ────────────────────────────────────────────────────

bool ping() {
  return true;
}

void set_text(String text) {
  matrix.beginDraw();
  matrix.clear();
  int len = text.length();
  int x = len <= 2 ? (13 - len * 5) / 2 : 0;
  matrix.textFont(Font_5x7);
  matrix.stroke(127, 127, 127);
  matrix.text(text.c_str(), x < 0 ? 0 : x, 1);
  matrix.endDraw();
}

void set_leds(int r1, int g1, int b1, int r2, int g2, int b2) {
  analogWrite(LED3_R, r1 & 0xFF);
  analogWrite(LED3_G, g1 & 0xFF);
  analogWrite(LED3_B, b1 & 0xFF);
  digitalWrite(LED4_R, r2 > 0 ? LOW : HIGH);
  digitalWrite(LED4_G, g2 > 0 ? LOW : HIGH);
  digitalWrite(LED4_B, b2 > 0 ? LOW : HIGH);
}

void clear_all() {
  matrix.beginDraw();
  matrix.clear();
  matrix.endDraw();
  analogWrite(LED3_R, 0);
  analogWrite(LED3_G, 0);
  analogWrite(LED3_B, 0);
  digitalWrite(LED4_R, HIGH);
  digitalWrite(LED4_G, HIGH);
  digitalWrite(LED4_B, HIGH);
}

// ── Setup / Loop ─────────────────────────────────────────────────────

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(LED3_R, OUTPUT);
  pinMode(LED3_G, OUTPUT);
  pinMode(LED3_B, OUTPUT);
  pinMode(LED4_R, OUTPUT);
  pinMode(LED4_G, OUTPUT);
  pinMode(LED4_B, OUTPUT);

  clear_all();

  matrix.begin();
  matrix.textFont(Font_5x7);
  matrix.stroke(127, 127, 127);
  matrix.clear();

  Bridge.begin();
  Bridge.provide("ping", ping);
  Bridge.provide("set_text", set_text);
  Bridge.provide("set_leds", set_leds);
  Bridge.provide("clear", clear_all);

  digitalWrite(LED_BUILTIN, HIGH);
}

void loop() {
  delay(10);
}
