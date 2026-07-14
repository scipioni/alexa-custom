## 1. Mosquitto Setup

- [x] 1.1 Create `setup/mosquitto-serena.conf` with `listener 1883` and `allow_anonymous true`
- [x] 1.2 Add `mqtt:setup` task: `apt install mosquitto`, copy conf to `/etc/mosquitto/conf.d/serena.conf`, `systemctl enable --now mosquitto`
- [x] 1.3 Add `mqtt:restart` task: `sudo systemctl restart mosquitto`
- [x] 1.4 Add `mqtt:status` task: `sudo systemctl status mosquitto`

## 2. Home Assistant Service Unit

- [x] 2.1 Create `setup/homeassistant.service` user service unit with `After=network-online.target mosquitto.service`, `ExecStart=%h/homeassistant/bin/hass -c %h/.homeassistant`, `Restart=on-failure`, `RestartSec=10s`

## 3. Home Assistant Taskfile Tasks

- [x] 3.1 Add `ha:setup` task:
    - `apt install` native build deps (`python3-dev python3-venv libffi-dev libssl-dev libjpeg-dev zlib1g-dev autoconf build-essential libopenjp2-7 libturbojpeg0-dev`)
    - Create venv at `~/homeassistant` only if it does not already exist
    - `~/homeassistant/bin/pip install homeassistant` (note 10–20 min in desc)
    - `mkdir -p ~/.homeassistant`
    - Copy service unit to `~/.config/systemd/user/homeassistant.service`
    - `systemctl --user daemon-reload`
    - `systemctl --user enable --now homeassistant`
- [x] 3.2 Add `ha:update` task: `~/homeassistant/bin/pip install --upgrade homeassistant`, then `systemctl --user restart homeassistant`
- [x] 3.3 Add `ha:restart` task: `systemctl --user restart homeassistant`
- [x] 3.4 Add `ha:status` task: `systemctl --user status homeassistant`

## 4. Verification

- [ ] 4.1 Run `task mqtt:setup` and verify `mosquitto_pub -h localhost -t test -m hello` succeeds
- [ ] 4.2 Run `task ha:setup` and verify HA web UI is accessible at `http://board:8123`
- [ ] 4.3 Enable `mqtt:` in `conf/config.yaml` pointing to `127.0.0.1:1883`, start Serena, and verify HA Discovery entities appear in HA
- [ ] 4.4 Reboot the board and verify both services come back up automatically
