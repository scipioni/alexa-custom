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

// ── 5×7 bitmap font (ASCII 0x20–0x7E) ──────────────────────────────
// Each char is 5 bytes (columns), bits 0-6 = rows 0-6 (LSB=top).
// Converted from alexa_custom/display_fonts.py

static const uint8_t PROGMEM font5x7[475] = {
  0x00,0x00,0x00,0x00,0x00, 0x00,0x00,0x5F,0x00,0x00,
  0x00,0x07,0x00,0x07,0x00, 0x14,0x7F,0x14,0x7F,0x14,
  0x24,0x2A,0x7F,0x2A,0x12, 0x23,0x13,0x08,0x64,0x62,
  0x36,0x49,0x55,0x22,0x50, 0x00,0x05,0x03,0x00,0x00,
  0x00,0x1C,0x22,0x41,0x00, 0x00,0x41,0x22,0x1C,0x00,
  0x08,0x2A,0x1C,0x2A,0x08, 0x08,0x08,0x3E,0x08,0x08,
  0x00,0x50,0x30,0x00,0x00, 0x08,0x08,0x08,0x08,0x08,
  0x00,0x60,0x60,0x00,0x00, 0x20,0x10,0x08,0x04,0x02,
  0x3E,0x51,0x49,0x45,0x3E, 0x00,0x42,0x7F,0x40,0x00,
  0x42,0x61,0x51,0x49,0x46, 0x21,0x41,0x45,0x4B,0x31,
  0x18,0x14,0x12,0x7F,0x10, 0x27,0x45,0x45,0x45,0x39,
  0x3C,0x4A,0x49,0x49,0x30, 0x01,0x71,0x09,0x05,0x03,
  0x36,0x49,0x49,0x49,0x36, 0x06,0x49,0x49,0x29,0x1E,
  0x00,0x36,0x36,0x00,0x00, 0x00,0x56,0x36,0x00,0x00,
  0x00,0x08,0x14,0x22,0x41, 0x14,0x14,0x14,0x14,0x14,
  0x41,0x22,0x14,0x08,0x00, 0x02,0x01,0x51,0x09,0x06,
  0x32,0x49,0x79,0x41,0x3E, 0x7E,0x11,0x11,0x11,0x7E,
  0x7F,0x49,0x49,0x49,0x36, 0x3E,0x41,0x41,0x41,0x22,
  0x7F,0x41,0x41,0x22,0x1C, 0x7F,0x49,0x49,0x49,0x41,
  0x7F,0x09,0x09,0x01,0x01, 0x3E,0x41,0x41,0x51,0x32,
  0x7F,0x08,0x08,0x08,0x7F, 0x00,0x41,0x7F,0x41,0x00,
  0x20,0x40,0x41,0x3F,0x01, 0x7F,0x08,0x14,0x22,0x41,
  0x7F,0x40,0x40,0x40,0x40, 0x7F,0x02,0x04,0x02,0x7F,
  0x7F,0x04,0x08,0x10,0x7F, 0x3E,0x41,0x41,0x41,0x3E,
  0x7F,0x09,0x09,0x09,0x06, 0x3E,0x41,0x51,0x21,0x5E,
  0x7F,0x09,0x19,0x29,0x46, 0x46,0x49,0x49,0x49,0x31,
  0x01,0x01,0x7F,0x01,0x01, 0x3F,0x40,0x40,0x40,0x3F,
  0x1F,0x20,0x40,0x20,0x1F, 0x7F,0x20,0x18,0x20,0x7F,
  0x63,0x14,0x08,0x14,0x63, 0x03,0x04,0x78,0x04,0x03,
  0x61,0x51,0x49,0x45,0x43, 0x00,0x00,0x7F,0x41,0x41,
  0x02,0x04,0x08,0x10,0x20, 0x41,0x41,0x7F,0x00,0x00,
  0x04,0x02,0x01,0x02,0x04, 0x40,0x40,0x40,0x40,0x40,
  0x00,0x01,0x02,0x04,0x00, 0x20,0x54,0x54,0x54,0x78,
  0x7F,0x48,0x44,0x44,0x38, 0x38,0x44,0x44,0x44,0x20,
  0x38,0x44,0x44,0x48,0x7F, 0x38,0x54,0x54,0x54,0x18,
  0x08,0x7E,0x09,0x01,0x02, 0x08,0x14,0x54,0x54,0x3C,
  0x7F,0x08,0x04,0x04,0x78, 0x00,0x44,0x7D,0x40,0x00,
  0x20,0x40,0x44,0x3D,0x00, 0x00,0x7F,0x10,0x28,0x44,
  0x00,0x41,0x7F,0x40,0x00, 0x7C,0x04,0x18,0x04,0x78,
  0x7C,0x08,0x04,0x04,0x78, 0x38,0x44,0x44,0x44,0x38,
  0x7C,0x14,0x14,0x14,0x08, 0x08,0x14,0x14,0x18,0x7C,
  0x7C,0x08,0x04,0x04,0x08, 0x48,0x54,0x54,0x54,0x20,
  0x04,0x3F,0x44,0x40,0x20, 0x3C,0x40,0x40,0x20,0x7C,
  0x1C,0x20,0x40,0x20,0x1C, 0x3C,0x40,0x30,0x40,0x3C,
  0x44,0x28,0x10,0x28,0x44, 0x0C,0x50,0x50,0x50,0x3C,
  0x44,0x64,0x54,0x4C,0x44, 0x00,0x08,0x36,0x41,0x00,
  0x00,0x00,0x7F,0x00,0x00, 0x00,0x41,0x36,0x08,0x00,
  0x08,0x08,0x2A,0x1C,0x08,
};

// ── IDLE: smiley face ────────────────────────────────────────────────

static const uint8_t PROGMEM smiley[8][13] = {
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,1,1,0,0,0,1,1,0,0,0},
  {0,0,0,1,1,0,0,0,1,1,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,1,0,0,0,0,0,1,0,0,0},
  {0,0,0,0,1,1,1,1,1,0,0,0,0},
  {0,0,0,0,0,0,0,0,0,0,0,0,0},
};

// ── SOUND WAVE: VU-meter equalizer, 6 frames ─────────────────────────
// 6 vertical bars at columns 0,2,4,6,8,10 (every other column).
// Heights vary to look like a wave sweeping.

static const uint8_t PROGMEM wave_frames[6][8][13] = {
  { // wave pos 0: mountain shape
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,1,0,1,0,0,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
  },
  { // wave pos 1: growing
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,1,0,0,0,0,0,0,0,1,0,0},
    {1,0,1,0,1,0,0,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
  },
  { // wave pos 2: peak
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,1,0,0,0,0,0,0,0,1,0,0},
    {1,0,1,0,1,0,0,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
  },
  { // wave pos 3: shrinking (mirror of pos 1)
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,1,0,0,0,0,0,0,0,1,0,0},
    {1,0,1,0,1,0,0,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
  },
  { // wave pos 4: mountain (mirror of pos 0)
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,1,0,1,0,0,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
  },
  { // wave pos 5: low (pause)
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,1,0,1,0,0,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
    {1,0,1,0,1,0,1,0,1,0,1,0,0},
  },
};

// ── THINKING: rotating gear, 4 frames ────────────────────────────────

static const uint8_t PROGMEM gear_frames[4][8][13] = {
  { // gear rot 0: teeth at vertical/horizontal
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,1,0,0,0,0,0,0},
    {0,0,0,0,0,1,1,1,0,0,0,0,0},
    {0,0,0,0,1,0,1,0,1,0,0,0,0},
    {0,0,0,0,1,0,1,0,1,0,0,0,0},
    {0,0,0,0,0,1,1,1,0,0,0,0,0},
    {0,0,0,0,0,0,1,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // gear rot 1: teeth at diagonals
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,1,0,0,0,0,0,0,0},
    {0,0,0,0,0,1,0,1,0,0,0,0,0},
    {0,0,0,0,1,0,0,0,1,0,0,0,0},
    {0,0,0,0,1,0,0,0,1,0,0,0,0},
    {0,0,0,0,0,1,0,1,0,0,0,0,0},
    {0,0,0,0,0,0,1,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // gear rot 2: teeth at horizontal/vertical (inverse of rot 0)
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,1,0,0,0,0,0,0},
    {0,0,0,0,0,1,0,1,0,0,0,0,0},
    {0,0,0,0,1,1,0,1,1,0,0,0,0},
    {0,0,0,0,1,1,0,1,1,0,0,0,0},
    {0,0,0,0,0,1,0,1,0,0,0,0,0},
    {0,0,0,0,0,0,1,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
  },
  { // gear rot 3: diagonals (inverse of rot 1)
    {0,0,0,0,0,0,0,0,0,0,0,0,0},
    {0,0,0,0,0,0,0,1,0,0,0,0,0},
    {0,0,0,0,0,1,0,1,0,0,0,0,0},
    {0,0,0,0,1,0,0,0,1,0,0,0,0},
    {0,0,0,0,1,0,0,0,1,0,0,0,0},
    {0,0,0,0,0,1,0,1,0,0,0,0,0},
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

// ── Scroll engine ─────────────────────────────────────────────────────

#define MAX_SCROLL_COLS 200

static uint8_t scroll_buf[MAX_SCROLL_COLS];
static int scroll_total_cols = 0;
static int scroll_offset = -13;
static int scroll_speed_ms = 100;
static bool scrolling = false;
static unsigned long scroll_last_tick = 0;

static const char* scroll_fallback = "";

static void render_text_to_buffer(const char* text) {
  memset(scroll_buf, 0, MAX_SCROLL_COLS);
  int col = 0;
  while (*text && col < MAX_SCROLL_COLS - 6) {
    char ch = *text++;
    if (ch < 0x20 || ch > 0x7E) {
      col += 6;
      continue;
    }
    int idx = (ch - 0x20) * 5;
    for (int c = 0; c < 5 && col < MAX_SCROLL_COLS; c++) {
      scroll_buf[col++] = pgm_read_byte(&font5x7[idx + c]);
    }
    col += 1;
  }
  scroll_total_cols = col;
}

static void draw_scroll_frame() {
  uint8_t frame[8][13] = {0};
  for (int x = 0; x < 13; x++) {
    int src_col = scroll_offset + x;
    if (src_col >= 0 && src_col < scroll_total_cols) {
      uint8_t col_data = scroll_buf[src_col];
      for (int y = 0; y < 7; y++) {
        if (col_data & (1 << y)) {
          frame[y][x] = 1;
        }
      }
    }
  }
  draw_frame(frame);
}

// ── State machine ───────────────────────────────────────────────────

static int _current_icon = -1;
static bool _animating = false;
static int _anim_count = 0;
static int _anim_frame = 0;
static int _anim_direction = 1;
static unsigned long _last_tick = 0;
static int _anim_tick_ms = 150;

// ── RPC providers ───────────────────────────────────────────────────

bool ping() {
  return true;
}

void set_icon(int icon_id) {
  scrolling = false;
  _animating = false;
  _current_icon = icon_id;
  switch (icon_id) {
    case ICON_IDLE:
      draw_frame(smiley);
      break;
    case ICON_LISTENING:
    case ICON_SPEAKING:
      _animating = true;
      _anim_count = 6;
      _anim_frame = 0;
      _anim_direction = 1;
      _last_tick = 0;
      draw_frame(wave_frames[0]);
      break;
    case ICON_THINKING:
      _animating = true;
      _anim_count = 4;
      _anim_frame = 0;
      _anim_direction = 1;
      _last_tick = 0;
      draw_frame(gear_frames[0]);
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
      draw_frame(smiley);
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

void scroll_text(String text, int speed_ms) {
  scrolling = false;
  _animating = false;
  render_text_to_buffer(text.c_str());
  scroll_offset = -13;
  scroll_speed_ms = speed_ms > 0 ? speed_ms : 100;
  scroll_last_tick = 0;
  if (scroll_total_cols > 0) {
    scrolling = true;
    draw_scroll_frame();
  }
}

void clear_all() {
  scrolling = false;
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
  Bridge.provide("scroll_text", scroll_text);
  Bridge.provide("clear", clear_all);
  scroll_text("Coop. Galileo", 100);
  digitalWrite(LED_BUILTIN, HIGH);
}

void loop() {
  if (scrolling) {
    unsigned long now = millis();
    if (now - scroll_last_tick >= (unsigned long)scroll_speed_ms) {
      scroll_last_tick = now;
      scroll_offset++;
      if (scroll_offset >= scroll_total_cols + 13) {
        scrolling = false;
        set_icon(ICON_IDLE);
        return;
      }
      draw_scroll_frame();
    }
  }
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
      if (_current_icon == ICON_LISTENING || _current_icon == ICON_SPEAKING) {
        draw_frame(wave_frames[_anim_frame]);
      } else if (_current_icon == ICON_THINKING) {
        draw_frame(gear_frames[_anim_frame]);
      }
    }
  }
  delay(10);
}
