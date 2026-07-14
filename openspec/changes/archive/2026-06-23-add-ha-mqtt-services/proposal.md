# Proposal: Add Home Assistant and Mosquitto as Systemd Services

## Problem

Serena already publishes Home Assistant Discovery messages over MQTT (`alexa_custom/mqtt.py`), but the broker and HA itself are not installed or managed by the project. Standing up these two services currently requires manual steps with no reproducible install path.

## Proposed Solution

Add two groups of Taskfile tasks — `mqtt:*` and `ha:*` — that install, configure, and manage Mosquitto and Home Assistant Core on the Arduino Uno Q board. Both follow the existing `setup/` + `systemctl` pattern used by `audio:setup` and `display:setup`.

### Mosquitto (MQTT broker)

- Installed via `apt install mosquitto`
- Configured with `allow_anonymous true` and `listener 1883` (binds all interfaces, no auth)
- Runs as a **system service** (`mosquitto.service`, provided by the package)
- Config drop-in placed at `/etc/mosquitto/conf.d/serena.conf`

### Home Assistant Core

- Installed as a Python venv at `~/homeassistant` (`pip install homeassistant`)
- Config/data directory at `~/.homeassistant`
- Runs as a **user service** (`~/.config/systemd/user/homeassistant.service`), consistent with `serena.service`
- Depends on `network-online.target` and `mosquitto.service`
- Serena remains **independent** — its MQTT client already retries on connection errors, so no `After=homeassistant.service` is added to `serena.service`

## Files to Add

| File | Purpose |
|------|---------|
| `setup/mosquitto-serena.conf` | Mosquitto drop-in: anonymous access, bind all interfaces |
| `setup/homeassistant.service` | Systemd user service unit for HA Core |

## Tasks to Add

| Task | Description |
|------|-------------|
| `mqtt:setup` | Install Mosquitto, drop config, enable system service |
| `mqtt:restart` | Restart Mosquitto system service |
| `mqtt:status` | Show Mosquitto system service status |
| `ha:setup` | Install native deps, create venv, pip install HA, install user service |
| `ha:update` | Upgrade HA to latest (`pip install --upgrade`) and restart |
| `ha:restart` | Restart HA user service |
| `ha:status` | Show HA user service status |

## Non-Goals

- Home Assistant configuration (automations, integrations) — done via HA web UI at `http://board:8123`
- Mosquitto authentication or TLS
- Modifying `serena.service` dependencies
- Docker-based HA install

## Success Criteria

- `task mqtt:setup` installs and starts Mosquitto; `mosquitto_pub`/`mosquitto_sub` work on port 1883 from any LAN host
- `task ha:setup` installs HA Core and starts it; HA web UI is accessible at `http://board:8123`
- Serena connects to the broker and publishes HA Discovery topics without modification
- `task ha:update` upgrades HA in-place and restarts the service
