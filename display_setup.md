# Visual Display Setup Guide — Arduino UNO Q

This guide walks through everything needed to enable visual feedback
on the Arduino UNO Q's built-in LED matrix (8×13) and RGB LEDs.

## Overview

| Layer | Hardware | Connection | Effort |
|-------|----------|------------|--------|
| **MPU RGB LEDs** (×2) | `/sys/class/leds/` | Zero setup — works immediately | None |
| **Matrix + MCU LEDs** (×2) | UART → RouterBridge → TCP:7501 | Flash firmware + Router config | ~15 min |

## Quick Start

```bash
# 1. Install Arduino libraries (one-time)
arduino-cli lib install Arduino_RouterBridge ArduinoGraphics

# 2. Compile and flash the STM32 firmware
cd ~/alexa-custom
arduino-cli compile --upload --fqbn arduino:zephyr:unoq \
  setup/display_firmware/display_firmware.ino

# 3. Enable display in config.yaml
echo 'display:
  enabled: true
  backend: auto' >> conf/config.yaml

# 4. Verify Router is listening on TCP 7501
ss -tlnp | grep 7501

# If not, fix the Router service (see §3 below)

# 5. Restart Router and test
sudo systemctl restart arduino-router
serena-client
```

## 1. Flash the STM32 firmware

### Via arduino-cli (recommended)

```bash
# Install required libraries
arduino-cli lib install Arduino_RouterBridge ArduinoGraphics

# Compile
arduino-cli compile --fqbn arduino:zephyr:unoq \
  setup/display_firmware/display_firmware.ino

# Upload (over network — board must be on same subnet)
echo 'y' | arduino-cli upload --fqbn arduino:zephyr:unoq \
  --port <BOARD_IP> setup/display_firmware/display_firmware.ino
```

### Via Arduino IDE

1. **File → Open** → `setup/display_firmware/display_firmware.ino`
2. **Tools → Board → Arduino UNO Q**
3. **Tools → Port** → select the UNO Q port
4. **Sketch → Upload**

## 2. Enable in config.yaml

```yaml
display:
  enabled: true
  backend: auto        # auto | bridge | gpio | mock | i2c
```

`auto` tries: bridge → gpio → i2c → mock.

## 3. Router service — TCP port 7501

The Router (`arduino-router`) bridges TCP ↔ UART to the STM32.
It must listen on **TCP port 7501** for `BridgeDisplay` to work.

### Verify

```bash
ss -tlnp | grep 7501
```

If empty, the Router might be running without `--listen-port`:

```bash
# Check active config
sudo systemctl cat arduino-router
```

### Fix missing TCP port

Some board images have a drop-in that overrides `ExecStart`:

```bash
# Create a higher-priority override
sudo mkdir -p /etc/systemd/system/arduino-router.service.d
sudo tee /etc/systemd/system/arduino-router.service.d/20-listen-port.conf << 'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/arduino-router \
  --unix-port /var/run/arduino-router.sock \
  --listen-port 0.0.0.0:7501 \
  --serial-port /dev/ttyHS1 \
  --serial-baudrate 115200 \
  --after-ready '/usr/bin/gpioset -c /dev/gpiochip1 -t0 70=1'
EOF

sudo systemctl daemon-reload
sudo systemctl restart arduino-router
```

### Start manually (for testing)

```bash
sudo pkill -x arduino-router
sudo /usr/bin/arduino-router \
  --unix-port /var/run/arduino-router.sock \
  --listen-port 0.0.0.0:7501 \
  --serial-port /dev/ttyHS1 \
  --serial-baudrate 115200 \
  --after-ready '/usr/bin/gpioset -c /dev/gpiochip1 -t0 70=1' &
```

## 4. Test display

```python
from alexa_custom.display import BridgeDisplay
d = BridgeDisplay(host="<BOARD_IP>", port=7501)
d.show("idle")        # eyes icon, blue LEDs
d.show("listening")   # scanning wave animation, green
d.show("llm_thinking")# hourglass, yellow
d.show("speaking")    # propagating bars, red
d.show("connected")   # checkmark, cyan
d.clear()
```

## 5. Troubleshooting

### "RPC timeout: ping" / Bridge ping failed

- Router not listening on TCP 7501 → see §3
- STM32 firmware not flashed → see §1
- Router stale after flash → `sudo systemctl restart arduino-router`

### Missing Arduino libraries

```bash
arduino-cli lib search Arduino_RouterBridge
arduino-cli lib install Arduino_RouterBridge
arduino-cli lib install ArduinoGraphics
```

### Different core version

```bash
arduino-cli core update
arduino-cli core upgrade
```

### Permission denied

```bash
sudo usermod -aG dialout $USER
# log out and back in
```

## Icon reference

| State | Icon | LED colour | Animation |
|-------|------|------------|-----------|
| `idle` | 👁️👁️ eyes | Blue | Static |
| `listening` / `wake` | `‖` scanning bar | Green | 6-frame ping-pong |
| `llm_thinking` | ⏳ hourglass | Yellow | Static |
| `speaking` / `llm_reply` | `‖→‖→‖` propagating bars | Red | 5-frame cycle |
| `nomatch` | ✕ X | Red | Static |
| `connected` | ✓ checkmark | Cyan | Static |
| `gated` | ☎ phone handset | Purple | Static |
| `disconnected` | blank | Off | — |
| `starting` | ✓ checkmark | Orange | Static |

## I2C OLED display (optional)

Connect an SSD1306 (128×64) to the Snapdragon I2C pins:

```bash
pip install smbus2
```

Config:

```yaml
display:
  enabled: true
  backend: i2c
  i2c_bus: 1
  i2c_address: '0x3C'
```
