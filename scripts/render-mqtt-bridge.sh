#!/usr/bin/env bash
# Render setup/mosquitto-bridge.conf.template into /etc/mosquitto/conf.d/,
# substituting the bridge credentials from conf/secrets.yaml and this board's
# hostname (the remote namespace root — see docs/mqtt_integration.md).
#
# The credentials cannot live in setup/mosquitto-serena.conf (committed), and
# they cannot live in a separate conf.d drop-in either: mosquitto tracks the
# current bridge per config file, so a `username` line outside the file holding
# `connection ...` fails with "Error: Invalid bridge configuration". Hence a
# template rendered into a root-owned file at deploy time.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$REPO_ROOT/setup/mosquitto-bridge.conf.template"
SECRETS="${SERENA_SECRETS:-$REPO_ROOT/conf/secrets.yaml}"
TARGET="${MQTT_BRIDGE_CONF:-/etc/mosquitto/conf.d/serena-bridge.conf}"

[[ -f "$TEMPLATE" ]] || { echo "Template not found: $TEMPLATE" >&2; exit 1; }
[[ -f "$SECRETS" ]] || {
  echo "Secrets file not found: $SECRETS" >&2
  echo "Add mqtt.bridge_username / mqtt.bridge_password (see conf.example/secrets.yaml)." >&2
  exit 1
}

# Read the two values with a YAML parser rather than grep: passwords legitimately
# contain ':', '#' and '@'. Printed NUL-separated so nothing is line-mangled.
mapfile -d '' -t CREDS < <(python3 - "$SECRETS" <<'PY'
import sys, yaml
raw = yaml.safe_load(open(sys.argv[1])) or {}
mqtt = raw.get("mqtt") or {}
for key in ("bridge_username", "bridge_password"):
    value = mqtt.get(key)
    if not value:
        sys.exit(f"conf/secrets.yaml: mqtt.{key} is missing or empty")
    sys.stdout.write(str(value) + "\0")
PY
)
# A failure inside the process substitution above cannot fail this script (its
# exit status is not part of the pipeline), so check what actually came back —
# otherwise the reason is followed by a confusing "unbound variable".
if [[ ${#CREDS[@]} -ne 2 ]]; then
  echo "Could not read mqtt.bridge_username / mqtt.bridge_password from $SECRETS" >&2
  exit 1
fi
USERNAME="${CREDS[0]}"
PASSWORD="${CREDS[1]}"
# Same value alexa_custom/mqtt.py falls back to for node_id (socket.gethostname()) —
# this is the remote namespace root (hub/<hostname>, cmd/serena/<hostname>/...).
HOSTNAME_VALUE="${SERENA_BRIDGE_HOSTNAME:-$(hostname)}"

# Substitute in python too — sed would treat '&', '\' and the delimiter in a
# password as syntax.
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
BRIDGE_USERNAME="$USERNAME" BRIDGE_PASSWORD="$PASSWORD" BRIDGE_HOSTNAME="$HOSTNAME_VALUE" \
  python3 - "$TEMPLATE" >"$TMP" <<'PY'
import os, sys
text = open(sys.argv[1]).read()
for name in ("BRIDGE_USERNAME", "BRIDGE_PASSWORD", "BRIDGE_HOSTNAME"):
    text = text.replace(f"@{name}@", os.environ[name])
sys.stdout.write(text)
PY

if grep -q '@BRIDGE_[A-Z_]*@' "$TMP"; then
  echo "Unsubstituted placeholder left in the rendered config — aborting." >&2
  exit 1
fi

# 640 owner mosquitto: the broker must read it, nobody else should.
sudo install -o mosquitto -g root -m 640 "$TMP" "$TARGET"
echo "Rendered $TARGET (owner mosquitto, mode 640) for bridge user '$USERNAME', hostname '$HOSTNAME_VALUE'."
