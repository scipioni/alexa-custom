# Home Assistant Setup

This guide covers installing Mosquitto (MQTT broker) and Home Assistant Core as systemd services on the Arduino Uno Q board, then connecting Serena to them.

For the integration reference (entities, topics, automation examples) see [MQTT & HA Integration](mqtt_integration.md).

---

## Overview

```
Serena (user service)
    │
    │ publishes HA Discovery + state/command topics
    ▼
Mosquitto  :1883  (system service, all interfaces)
    │
    │ MQTT
    ▼
Home Assistant  :8123  (user service)
```

Both services are managed by the Taskfile and start automatically on boot.

---

## 1. Install Mosquitto

```bash
task mqtt:setup
```

This installs the `mosquitto` package, drops a config that binds to all interfaces with anonymous access, and enables the system service.

**Verify:**
```bash
task mqtt:status
mosquitto_pub -h localhost -t test/ping -m hello
mosquitto_sub -h localhost -t test/ping
```

The broker is reachable at port `1883` from any host on the LAN — no authentication required.

---

## 2. Install Home Assistant Core

```bash
task ha:setup
```

> **Note:** First install takes **10–20 minutes** on the aarch64 board — pip builds several native wheels from source. Leave it running.

This task:
1. Installs native build dependencies via `apt`
2. Creates a Python venv at `~/homeassistant` (skipped if it already exists)
3. Runs `pip install homeassistant`
4. Installs `~/.config/systemd/user/homeassistant.service` and enables it

**Verify:**
```bash
task ha:status
# Wait ~30 s for first-run init, then:
curl -s http://localhost:8123 | head -5
```

---

## 3. HA Onboarding

On first start, HA runs an onboarding wizard. Open a browser and go to:

```
http://<board-hostname-or-ip>:8123
```

Create an account and complete the setup wizard. HA will be ready to use after this step.

### Add the MQTT Integration

In HA: **Settings → Devices & Services → Add Integration → MQTT**

- Broker: `127.0.0.1`
- Port: `1883`
- Leave username/password empty

Once saved, HA is listening for Discovery messages.

---

## 4. Connect Serena

Enable the `mqtt:` section in `conf/config.yaml`:

```yaml
mqtt:
  host: 127.0.0.1
  port: 1883
  topic_prefix: alexa
  node_id: living_room   # defaults to hostname if omitted
```

Restart Serena:

```bash
systemctl --user restart serena
```

Serena publishes HA Discovery on startup. Within a few seconds, three entities appear in HA under **Settings → Devices & Services → MQTT**:

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.<node_id>_status` | Sensor | `idle` / `listening` / `speaking` / `in_call` |
| `sensor.<node_id>_command` | Sensor | Last recognized voice command |
| `text.<node_id>_tts` | Text | Type text here → Serena speaks it |

---

## 5. Service Management

### Mosquitto

```bash
task mqtt:status    # service status
task mqtt:restart   # restart broker
journalctl -fu mosquitto  # follow logs
```

### Home Assistant

```bash
task ha:status      # service status
task ha:restart     # restart HA
task ha:update      # upgrade to latest HA version
journalctl --user -fu homeassistant  # follow logs
```

---

## 6. Upgrading Home Assistant

```bash
task ha:update
```

This runs `pip install --upgrade homeassistant` in the venv and restarts the service. HA performs any database migrations automatically on startup.

Check the [HA release notes](https://www.home-assistant.io/blog/) before upgrading — breaking changes are documented there.
