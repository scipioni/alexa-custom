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

// ── Icon IDs ─────────────────────────────────────────────────────────

enum IconId {
  ICON_IDLE = 0,
  ICON_LISTENING = 1,
  ICON_THINKING = 2,
  ICON_SPEAKING = 3,
  ICON_NOMATCH = 4,
  ICON_CONNECTED = 5,
  ICON_DISCONNECTED = 6,
  ICON_GATED = 7,
  ICON_STARTING = 8,
};

// ── Draw helpers ─────────────────────────────────────────────────────

static void draw_frame(const uint8_t (*data)[13]) {
  matrix.beginDraw();
  matrix.clear();
  for (int y = 0; y < 8; y++)
    for (int x = 0; x < 13; x++)
      if (pgm_read_byte(&data[y][x]))
        matrix.set(x, y, 255, 255, 255);
  matrix.endDraw();
}

// ── IDLE: eyes with pupils ───────────────────────────────────────────

static const uint8_t PROGMEM idle_eye[8][13] = {
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,1,1,1,0,1,1,1,0,0},
  {0,0,0,1,0,0,1,0,1,0,0,1,0},
  {0,0,0,0,1,1,1,0,1,1,1,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
};

// ── LISTENING: wave scanning left-to-right, 6 frames ─────────────────
// A 4-pixel-tall bar that moves across columns. Bar at (cols x,x+1).

static const uint8_t PROGMEM listen_frames[6][8][13] = {
  { // scan pos 0: cols 0-1
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {1,1,0,0,0,0,0,0,0,0,0,0,0},
    {1,1,0,0,0,0,0,0,0,0,0,0,0},
    {1,1,0,0,0,0,0,0,0,0,0,0,0},
    {1,1,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // scan pos 1: cols 2-3
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,1,1,0,0,0,0,0,0,0,0,0},
    {0,0,1,1,0,0,0,0,0,0,0,0,0},
    {0,0,1,1,0,0,0,0,0,0,0,0,0},
    {0,0,1,1,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // scan pos 2: cols 4-5
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,1,1,0,0,0,0,0,0,0},
    {0,0,0,0,1,1,0,0,0,0,0,0,0},
    {0,0,0,0,1,1,0,0,0,0,0,0,0},
    {0,0,0,0,1,1,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // scan pos 3: cols 6-7
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,1,1,0,0,0,0,0},
    {0,0,0,0,0,0,1,1,0,0,0,0,0},
    {0,0,0,0,0,0,1,1,0,0,0,0,0},
    {0,0,0,0,0,0,1,1,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // scan pos 4: cols 8-9
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,1,1,0,0,0},
    {0,0,0,0,0,0,0,0,1,1,0,0,0},
    {0,0,0,0,0,0,0,0,1,1,0,0,0},
    {0,0,0,0,0,0,0,0,1,1,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // scan pos 5: cols 10-11
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,1,1,0},
    {0,0,0,0,0,0,0,0,0,0,1,1,0},
    {0,0,0,0,0,0,0,0,0,0,1,1,0},
    {0,0,0,0,0,0,0,0,0,0,1,1,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
};

// ── THINKING: hourglass static ──────────────────────────────────────

static const uint8_t PROGMEM hourglass[8][13] = {
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,1,1,1,1,1,0,0,0,0},
  {0,0,0,1,0,0,0,0,0,1,0,0,0},
  {0,0,1,0,0,1,1,0,0,0,1,0,0},
  {0,0,0,1,0,1,1,0,1,0,0,0,0},
  {0,0,0,0,1,0,0,1,0,0,0,0,0},
  {0,0,0,0,0,1,1,0,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
};

// ── SPEAKING: bars propagating left to right, 4 frames ──────────────
// A wave-front with trailing bars of decreasing height.

static const uint8_t PROGMEM speak_frames[5][8][13] = {
  { // wave front at cols 0-1, h=6
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {1,1,0,0,0,0,0,0,0,0,0,0,0},
    {1,1,0,0,0,0,0,0,0,0,0,0,0},
    {1,1,0,0,0,0,0,0,0,0,0,0,0},
    {1,1,0,0,0,0,0,0,0,0,0,0,0},
    {1,1,0,0,0,0,0,0,0,0,0,0,0},
    {1,1,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // wave at cols 4-5, trail at cols 2-3 (h=3)
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,1,1,1,1,0,0,0,0,0,0,0},
    {0,0,1,1,1,1,0,0,0,0,0,0,0},
    {0,0,0,0,1,1,0,0,0,0,0,0,0},
    {0,0,0,0,1,1,0,0,0,0,0,0,0},
    {0,0,0,0,1,1,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // wave at cols 7-8, trail at cols 5-6 (h=3)
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,1,1,1,1,0,0,0},
    {0,0,0,0,0,0,1,1,1,1,0,0,0},
    {0,0,0,0,0,0,1,1,1,1,0,0,0},
    {0,0,0,0,0,0,0,0,1,1,0,0,0},
    {0,0,0,0,0,0,0,0,1,1,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // wave at cols 10-11, trail at cols 8-9 (h=3)
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,1,1,1,1,0},
    {0,0,0,0,0,0,0,0,1,1,1,1,0},
    {0,0,0,0,0,0,0,0,0,0,1,1,0},
    {0,0,0,0,0,0,0,0,0,0,1,1,0},
    {0,0,0,0,0,0,0,0,0,0,1,1,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // final: silence
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
};

// ── CONNECTED: check mark ────────────────────────────────────────────

static const uint8_t PROGMEM checkmark[8][13] = {
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,1,0,0},
  {0,0,0,0,0,0,0,0,0,1,0,0,0},
  {0,0,0,0,0,0,0,1,1,0,0,0,0},
  {0,0,0,0,0,0,1,1,0,0,0,0,0},
  {0,0,0,0,1,1,0,0,0,0,0,0,0},
  {0,0,0,1,1,0,0,0,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
};

// ── NOMATCH: X ──────────────────────────────────────────────────────

static const uint8_t PROGMEM xmark[8][13] = {
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,0,1,0,1,0,0,0,0,0},
  {0,0,0,0,0,0,1,0,0,0,0,0,0},
  {0,0,0,0,0,0,1,0,0,0,0,0,0},
  {0,0,0,0,0,1,0,1,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
};

// ── GATED: phone handset ────────────────────────────────────────────

static const uint8_t PROGMEM phone[8][13] = {
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,1,1,1,1,1,0,0,0,0},
  {0,0,0,0,1,0,0,0,1,0,0,0,0},
  {0,0,0,0,1,0,0,0,1,0,0,0,0},
  {0,0,0,0,1,0,0,0,1,0,0,0,0},
  {0,0,0,0,0,1,1,1,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
};

// ── State machine ───────────────────────────────────────────────────

static int _current_icon = -1;
static bool _animating = false;
static int _anim_base = 0;
static int _anim_count = 0;
static int _anim_frames = 0;
static int _anim_frame = 0;
static int _anim_direction = 1;
static unsigned long _last_tick = 0;
static int _anim_tick_ms = 150;

// ── RPC providers ───────────────────────────────────────────────────

bool ping() {
  return true;
}

void set_icon(int icon_id) {
  _animating = false;
  _current_icon = icon_id;
  switch (icon_id) {
    case ICON_IDLE:
      draw_frame(idle_eye);
      break;
    case ICON_LISTENING:
      _animating = true;
      _anim_count = 6;
      _anim_frame = 0;
      _anim_direction = 1;
      _last_tick = 0;
      draw_frame(listen_frames[0]);
      break;
    case ICON_THINKING:
      draw_frame(hourglass);
      break;
    case ICON_SPEAKING:
      _animating = true;
      _anim_count = 5;
      _anim_frame = 0;
      _anim_direction = 1;
      _last_tick = 0;
      draw_frame(speak_frames[0]);
      break;
    case ICON_NOMATCH:
      draw_frame(xmark);
      break;
    case ICON_CONNECTED:
      draw_frame(checkmark);
      break;
    case ICON_DISCONNECTED:
      matrix.clear();
      break;
    case ICON_GATED:
      draw_frame(phone);
      break;
    case ICON_STARTING:
      draw_frame(checkmark);
      break;
    default:
      break;
  }
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
  _animating = false;
  _current_icon = -1;
  matrix.clear();
  analogWrite(LED3_R, 0);
  analogWrite(LED3_G, 0);
  analogWrite(LED3_B, 0);
  digitalWrite(LED4_R, HIGH);
  digitalWrite(LED4_G, HIGH);
  digitalWrite(LED4_B, HIGH);
}

// ── Setup / Loop ────────────────────────────────────────────────────

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
  Bridge.begin();
  Bridge.provide("ping", ping);
  Bridge.provide("set_icon", set_icon);
  Bridge.provide("set_leds", set_leds);
  Bridge.provide("clear", clear_all);
  set_icon(ICON_IDLE);
  digitalWrite(LED_BUILTIN, HIGH);
}

void loop() {
  if (_animating) {
    unsigned long now = millis();
    if (now - _last_tick >= _anim_tick_ms) {
      _last_tick = now;
      _anim_frame += _anim_direction;
      if (_anim_frame >= _anim_count) {
        _anim_direction = -1;
        _anim_frame = _anim_count - 2;
      } else if (_anim_frame < 0) {
        _anim_direction = 1;
        _anim_frame = 1;
      }
      if (_current_icon == ICON_LISTENING) {
        draw_frame(listen_frames[_anim_frame]);
      } else if (_current_icon == ICON_SPEAKING) {
        draw_frame(speak_frames[_anim_frame]);
      }
    }
  }
  delay(10);
}
