# Visual Display Setup Guide — Arduino UNO Q

This guide walks through everything needed to enable visual feedback
on the Arduino UNO Q's built-in LED matrix (8×13) and RGB LEDs.

## Overview

Two layers of visual feedback:

| Layer | Hardware | Connection | Effort |
|-------|----------|------------|--------|
| **MPU RGB LEDs** (×2) | `/sys/class/leds/` | Zero setup — works immediately | None |
| **Matrix + MCU LEDs** (×2) | I²C via ArduinoRouterBridge | Requires flashing firmware once | ~15 min |

The MPU LEDs work *immediately* after enabling the feature in config.
The matrix and MCU LEDs need the firmware flashed once, then they work automatically too.

---

## 1. Enable in config.yaml

Add to `conf/config.yaml`:

```yaml
display:
  enabled: true
  backend: auto        # auto | bridge | gpio | mock
  matrix_brightness: 50
  led_brightness: 50
```

With `backend: auto`, the system tries Bridge → GPIO → Mock in order.

To verify it works without hardware (on your dev PC):

```yaml
display:
  enabled: true
  backend: mock
```

Check the logs for lines like `[display] listening | color=(0,255,0) | icon=🎤`.

---

## 2. Flash the STM32 firmware (one time only)

This step enables the LED matrix + MCU RGB LEDs. Skip if you only
want the MPU LEDs.

### 2.1 Install Arduino IDE 2.x

Download from https://www.arduino.cc/en/software

### 2.2 Add UNO Q board support

1. Open Arduino IDE → **File → Preferences**
2. In **Additional Boards Manager URLs**, add:
   ```
   https://raw.githubusercontent.com/Arduino/ArduinoCore-zephyr/main/package_arduino_zephyr_index.json
   ```
3. **Tools → Board → Boards Manager**
4. Search for "Arduino UNO Q" and install

### 2.3 Install required libraries

**Tools → Manage Libraries**, search and install:

| Library | Search term |
|---------|-------------|
| LED Matrix | `Arduino_LED_Matrix` |
| Router Bridge | `ArduinoRouterBridge` |

### 2.4 Open and flash the sketch

1. **File → Open** → navigate to `setup/display_firmware/display_firmware.ino`
2. Connect the UNO Q to your PC via USB
3. **Tools → Board** → select **Arduino UNO Q**
4. **Tools → Port** → select the UNO Q's serial port
5. Click **Upload** (→ arrow button)

After upload completes (15-30 seconds), the board will auto-reboot.
The LEDs will flash blue briefly, then show the idle icon (`◎`).

### 2.5 Verify the firmware works

On the UNO Q (SSH or App Lab), run:

```python
python3 -c "
from arduino.app_utils import Bridge
print('ping:', Bridge.call('ping'))
print('icon:', Bridge.call('set_matrix_icon', 1))
print('leds:', Bridge.call('set_leds', 0, 255, 0, 0, 255, 0))
input('Press Enter to clear...')
Bridge.call('clear')
print('Done')
"
```

Expected output: matrix shows mic icon, LEDs turn green, then clear on Enter.

---

## 3. Run alexa-custom with display enabled

Once the firmware is flashed and `display:` is in config.yaml,
run normally:

```bash
alexa-client
```

Expected behaviour:

| State | Matrix | LEDs |
|-------|--------|------|
| Idle (no wake word) | `◎` circle | Blue |
| Wake word detected | `🎤` mic | Green |
| Transcribing | `📝` equaliser | Green (blink) |
| LLM thinking | `⏳` spinner | Yellow |
| Speaking | `🔊` waves | Red |
| In LiveKit call | `📞` phone | Purple |
| Disconnected | off | Off |

---

## 4. Troubleshooting

### No display output at all

Check logs for:
```
[display] Bridge call failed
```
→ Firmware not flashed or Bridge not responding. Falls back to GPIO → Mock.

### Only MPU LEDs work (no matrix)

Bridge backend failed. Most likely: firmware not flashed, or
`arduino.app_utils` not available (App Lab environment only).

Check: `python3 -c "from arduino.app_utils import Bridge; print(Bridge.call('ping'))"`

### Permission denied on `/sys/class/leds/`

Run alexa-custom as root or add your user to the `video` group:

```bash
sudo usermod -aG video $USER
# log out and back in
```

### I want to customise the matrix icons

Edit `setup/display_firmware/display_firmware.ino` and modify the
bitmap arrays. Each icon is 13 bytes (column-major, 8 pixels per column).
After editing, re-flash the sketch.
