# Forked file map

Every file in this directory is a **byte-identical fork** of a source-of-truth
file elsewhere in the repo — forked, not symlinked, so `production/` stays
fetchable on its own (see `production/README.md`, "Fetching production/ onto
a board"). `task check:drift` (root `Taskfile.yml`) diffs each pair below and
fails on any difference — run it after touching either side.

No per-file header comments are added on this side: that would make every
fork differ from its source by definition, defeating a byte-identical diff.
This file is the single place the mapping is recorded.

| Fork (this directory)                | Source of truth                          |
|---------------------------------------|-------------------------------------------|
| `usb-audio-restore.sh`                | `setup/usb-audio-restore.sh`              |
| `99-usb-audio-no-autosuspend.rules`   | `setup/99-usb-audio-no-autosuspend.rules` |
| `usb-audio-autosuspend.service`       | `setup/usb-audio-autosuspend.service`     |
| `alsa-pcm-unmute.service`             | `setup/alsa-pcm-unmute.service`           |
| `51-usb-audio-no-suspend.conf`        | `setup/51-usb-audio-no-suspend.conf`      |
| `mosquitto-serena.conf`               | `setup/mosquitto-serena.conf`             |
| `mosquitto-bridge.conf.template`      | `setup/mosquitto-bridge.conf.template`    |
| `render-mqtt-bridge.sh`               | `scripts/render-mqtt-bridge.sh`           |

`render-mqtt-bridge.sh` is the one intentional exception — see the comment at
the top of that file for the small, deliberate diff (default secrets path).
