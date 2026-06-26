## Context

The board is an Arduino Uno Q (aarch64, Debian 13) running Serena as a systemd user service. Serena already has an MQTT client (`alexa_custom/mqtt.py`) that publishes Home Assistant Discovery topics and connects to `127.0.0.1:1883`. Neither the broker nor HA are installed — they need to be provisioned by the project's Taskfile in the same reproducible style as `audio:setup` and `display:setup`.

The existing pattern:
- System services → `sudo cp setup/X.service /etc/systemd/system/` + `sudo systemctl enable --now`
- User services → `cp setup/X.service ~/.config/systemd/user/` + `systemctl --user enable --now`

Linger is already enabled for the `arduino` user (`loginctl show-user arduino` → `Linger=yes`), so user services start on boot without a login session.

## Goals / Non-Goals

**Goals:**
- `task mqtt:setup` installs and starts Mosquitto, reachable at `:1883` from any LAN host
- `task ha:setup` installs HA Core in `~/homeassistant` venv, starts it as a user service, web UI at `:8123`
- `task ha:update` upgrades HA in-place without reinstalling from scratch
- Convenience tasks: `mqtt:restart`, `mqtt:status`, `ha:restart`, `ha:status`
- Serena connects to the broker and publishes HA Discovery without any code changes

**Non-Goals:**
- Mosquitto authentication or TLS
- Pre-seeding `~/.homeassistant/configuration.yaml` (user configures HA via web UI)
- Docker-based HA install
- Modifying `serena.service` dependencies (Serena stays independent, retries MQTT on error)

## Decisions

### D1 — Mosquitto as system service, HA as user service

**Decision**: Mosquitto runs as a system service; Home Assistant runs as a user service.

**Rationale**: Mosquitto is a system-level daemon that creates its own OS user and writes to `/var/log` and `/var/run/mosquitto`. The package ships a ready-made `mosquitto.service` system unit — no custom unit needed. HA, by contrast, owns its config at `~/.homeassistant` (user-scoped) and follows the same pattern as `serena.service`. User service avoids running HA as root and keeps all its state under the `arduino` home directory.

### D2 — Mosquitto binds to 0.0.0.0, no auth

**Decision**: `listener 1883` (all interfaces) + `allow_anonymous true`.

**Rationale**: The board is a home automation hub. Other LAN devices (ESPHome nodes, sensors, other boards) need to publish/subscribe. The network boundary (home LAN + router firewall) is the security perimeter, not the broker. A config drop-in at `/etc/mosquitto/conf.d/serena.conf` avoids touching the distro-owned `/etc/mosquitto/mosquitto.conf`.

### D3 — HA Core venv at ~/homeassistant, data at ~/.homeassistant

**Decision**: Venv lives at `~/homeassistant`; HA data/config at `~/.homeassistant`.

**Rationale**: Mirrors the project's own layout (`~/serena` for the project, `conf/` for data). Keeps everything user-scoped, no `/opt` with root ownership. The venv path is short and predictable for the service unit (`%h/homeassistant/bin/hass`).

`ha:setup` skips venv creation if `~/homeassistant` already exists (idempotent re-runs).

### D4 — HA depends on mosquitto.service, Serena stays independent

**Decision**: `homeassistant.service` has `After=mosquitto.service`; `serena.service` is unchanged.

**Rationale**: HA needs the broker to be up before starting its MQTT integration. Serena's MQTT client already retries on `MqttError` with a 5-second backoff — it tolerates a slow-starting broker. Adding `After=homeassistant.service` to Serena would block Serena startup on HA boot time (~30–60 s on first run), which is undesirable for a voice assistant.

### D5 — Native deps installed by ha:setup

**Decision**: `ha:setup` installs the full set of Debian native build dependencies before creating the venv.

**Rationale**: HA Core on aarch64 builds several wheels from source (`cryptography`, `pillow`, `aiohttp`, etc.). Missing build deps cause mid-install failures that are hard to diagnose. Installing them upfront is safe (apt is idempotent) and guarantees a clean install.

Dep list (from official HA Core Debian guide):
`python3-dev python3-venv libffi-dev libssl-dev libjpeg-dev zlib1g-dev autoconf build-essential libopenjp2-7 libturbojpeg0-dev`

### D6 — ha:setup warns about install time

**Decision**: The `ha:setup` task desc notes "takes 10–20 min on first install (aarch64 builds native wheels)."

**Rationale**: HA pulls ~200 packages and builds several native extensions. Silent long waits on a headless board are confusing; a desc-level warning sets correct expectations.

## Configuration Files

### setup/mosquitto-serena.conf
```
# Serena drop-in: anonymous access, bind all interfaces
listener 1883
allow_anonymous true
```

### setup/homeassistant.service
```ini
[Unit]
Description=Home Assistant
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h
ExecStart=%h/homeassistant/bin/hass -c %h/.homeassistant
Restart=on-failure
RestartSec=10s
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

## Risks / Trade-offs

- **[HA install time]** `pip install homeassistant` can take 15–20 min on aarch64. `ha:setup` should print a progress note before the pip step so the user knows it's running.
- **[HA Python compatibility]** HA Core requires Python ≥ 3.12. Board has Python 3.13.5 — compatible. If Python is ever downgraded below 3.12, HA install will fail.
- **[Mosquitto 2.x requires explicit allow_anonymous]** Mosquitto 2.0+ ships with `allow_anonymous false` and no listener by default. Without the drop-in, the service starts but rejects all connections silently. The `serena.conf` drop-in explicitly sets both options.
- **[HA first-run init]** On first start, HA runs its onboarding wizard. It does not fail — it just waits for the user to visit `:8123`. No action needed from the task.
