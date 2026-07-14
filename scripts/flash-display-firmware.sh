#!/bin/bash
# Flash display firmware to Arduino UNO Q
set -euo pipefail

BOARD_FQBN="arduino:zephyr:unoq"
SKETCH_DIR="$(dirname "$(readlink -f "$0")")/../setup/display_firmware"
LIBS=("Arduino_RouterBridge@0.4.2" "ArduinoGraphics")
TIMEOUT_SECS=60

log() { echo "[flash-firmware] $*" >&2; }
warn() { echo "[flash-firmware] WARNING: $*" >&2; }
die() { echo "[flash-firmware] ERROR: $*" >&2; exit 1; }

need_bin() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

need_bin arduino-cli
need_bin realpath

find_port() {
    local ports
    ports=$(arduino-cli board list --format json 2>/dev/null | \
        python3 -c "
import sys, json
data = json.load(sys.stdin)
for item in data.get('detected_ports', []):
    for dev in item.get('matching_boards', []):
        if 'unoq' in dev.get('name', '').lower() or 'UNO Q' in dev.get('name', ''):
            addr = item.get('port', {}).get('address')
            sn = item.get('port', {}).get('properties', {}).get('serialNumber', '')
            if addr:
                print(f'{addr} {sn}')
                sys.exit(0)
for p in data.get('ports', []):
    for dev in p.get('boards', []):
        if 'unoq' in dev.get('name', '').lower() or 'UNO Q' in dev.get('name', ''):
            addr = p.get('address')
            sn = p.get('properties', {}).get('serialNumber', '')
            if addr:
                print(f'{addr} {sn}')
                sys.exit(0)
" 2>/dev/null || true)

    if [[ -n "$ports" ]]; then
        echo "$ports"
        return 0
    fi
    return 1
}

wait_for_board() {
    log "Waiting up to ${TIMEOUT_SECS}s for UNO Q to be connected..."
    local port=""
    local elapsed=0
    while (( elapsed < TIMEOUT_SECS )); do
        if port=$(find_port); then
            echo "$port"
            return 0
        fi
        sleep 2
        elapsed=$(( elapsed + 2 ))
    done
    return 1
}

install_lib() {
    local lib="$1"
    local name="${lib%@*}"
    local version="${lib##*@}"

    if [[ -d "${HOME}/Arduino/libraries/${name}" ]] || \
       arduino-cli lib list 2>/dev/null | grep -q "^${name} "; then
        log "Library $name already installed, skipping"
        return 0
    fi

    log "Installing library: $name (version: ${version:-latest})"
    if [[ "$version" != "$name" ]]; then
        arduino-cli lib install "$lib"
    else
        arduino-cli lib install "$lib"
    fi
}

install_all_libs() {
    log "Checking required libraries..."
    for lib in "${LIBS[@]}"; do
        install_lib "$lib"
    done
}

flash_firmware() {
    local port="$1"
    local sn="${2:-}"

    log "Compiling firmware..."
    arduino-cli compile \
        --fqbn "$BOARD_FQBN" \
        --output-dir "/tmp/arduino-build-$$" \
        "$SKETCH_DIR" || die "Compilation failed"

    log "Uploading to $port..."
    if [[ -n "$sn" ]]; then
        arduino-cli upload \
            -p "$port" \
            --fqbn "$BOARD_FQBN" \
            --input-dir "/tmp/arduino-build-$$" \
            --upload-property "upload.port.properties.serialNumber=$sn" || die "Upload failed"
    else
        arduino-cli upload \
            -p "$port" \
            --fqbn "$BOARD_FQBN" \
            --input-dir "/tmp/arduino-build-$$" || die "Upload failed"
    fi

    rm -rf "/tmp/arduino-build-$$"
    log "Upload complete!"
}

main() {
    install_all_libs

    local board_info
    if ! board_info=$(wait_for_board); then
        die "No UNO Q board found after ${TIMEOUT_SECS}s. Connect the board via USB and retry."
    fi

    local port sn
    read -r port sn <<< "$board_info"

    log "Found UNO Q at $port (Serial: $sn)"
    flash_firmware "$port" "$sn"
}

main "$@"
