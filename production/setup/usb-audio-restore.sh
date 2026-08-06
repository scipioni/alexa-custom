#!/bin/bash
# Device-agnostic USB conference-speakerphone restore for PipeWire/WirePlumber.
#
# Matches ANY USB audio card instead of hardcoding product names: PipeWire
# names USB audio objects alsa_card.usb-* / alsa_input.usb-* /
# alsa_output.usb-*, so NewPie, Yealink SP92/BT51, EMEET OfficeCore, and any
# other UAC speakerphone are all covered by the same patterns.
#
# Modes:
#   usb-audio-restore.sh                   restore mode (boot / audio:restart):
#                                          wait for the card, apply profile,
#                                          poll for the source, force default
#                                          routing, unmute hardware mixers.
#                                          An existing profile entry in
#                                          WirePlumber's state file is
#                                          RESPECTED, so manual per-device
#                                          overrides (e.g. pro-audio for a
#                                          direct-USB Yealink SP92) survive.
#   usb-audio-restore.sh --select-profile  setup mode (task audio:setup):
#                                          pick the best available profile,
#                                          write it to WirePlumber's state
#                                          file (overriding any stale entry),
#                                          then exit.
#
# Profile preference (best → worst):
#   output:analog-stereo+input:analog-stereo   nodes under Sources/Sinks,
#                                              PulseAudio clients wake them
#   output:analog-stereo+input:mono-fallback   Bluetooth-dongle devices
#                                              (Yealink BT51: input is the
#                                              SP92 radio mic)
#   any other combined output:*+input:*        unknown future devices
#   pro-audio                                  last resort (nodes may land
#                                              under Filters on some hardware)
#
# pactl on PipeWire 1.4.x cannot set some combined profiles by name
# ("No such entity"), so the choice is also written to WirePlumber's state
# file (~/.local/state/wireplumber/default-profile), which WirePlumber reads
# on restart and persists across reboots.

set -u

STATE_FILE="${HOME}/.local/state/wireplumber/default-profile"

log() { echo "usb-audio-restore: $*"; }

usb_card_name() {
    pactl list cards short 2>/dev/null | awk '$2 ~ /^alsa_card\.usb-/ {print $2; exit}'
}

usb_source_name() {
    pactl list sources short 2>/dev/null \
        | awk '$2 ~ /^alsa_input\.usb-/ && $2 !~ /\.monitor$/ {print $2; exit}'
}

usb_sink_name() {
    pactl list sinks short 2>/dev/null | awk '$2 ~ /^alsa_output\.usb-/ {print $2; exit}'
}

# ALSA card number of the first USB sound card (USB cards have a usbid file).
usb_alsa_card_num() {
    local d
    for d in /proc/asound/card[0-9]*; do
        if [ -f "$d/usbid" ]; then
            echo "${d#/proc/asound/card}"
            return 0
        fi
    done
    return 1
}

# Print available profile names for the given card, one per line.
card_profiles() {
    pactl list cards 2>/dev/null | awk -v card="$1" '
        /^Card #/        { incard = 0; inprof = 0 }
        $1 == "Name:" && $2 == card { incard = 1 }
        incard && /^\tProfiles:/    { inprof = 1; next }
        incard && inprof {
            if ($0 !~ /^\t\t/) { inprof = 0; next }
            line = $0
            sub(/^\t\t/, "", line)
            name = line
            sub(/: .*/, "", name)
            if (line !~ /available: no/) print name
        }
    '
}

choose_profile() {
    local profiles="$1" want combined
    for want in "output:analog-stereo+input:analog-stereo" \
                "output:analog-stereo+input:mono-fallback"; do
        if printf '%s\n' "$profiles" | grep -qx "$want"; then
            echo "$want"
            return 0
        fi
    done
    combined=$(printf '%s\n' "$profiles" | grep -m1 '^output:.*+input:' || true)
    if [ -n "$combined" ]; then
        echo "$combined"
        return 0
    fi
    if printf '%s\n' "$profiles" | grep -qx "pro-audio"; then
        echo "pro-audio"
        return 0
    fi
    return 1
}

write_state_profile() { # $1 = card name, $2 = profile
    mkdir -p "$(dirname "$STATE_FILE")"
    [ -f "$STATE_FILE" ] || printf '[default-profile]\n' > "$STATE_FILE"
    if grep -q "^$1=" "$STATE_FILE" 2>/dev/null; then
        sed -i "s|^$1=.*|$1=$2|" "$STATE_FILE"
    else
        echo "$1=$2" >> "$STATE_FILE"
    fi
}

# Set every volume-capable simple mixer control on the card to 100% + unmute.
# Volume-only filter avoids flipping unrelated pure switches (e.g. hardware
# AGC toggles) that "unmute" would otherwise turn on.
unmute_all_controls() { # $1 = ALSA card number
    local card="$1" ctl caps
    amixer -c "$card" scontrols 2>/dev/null \
        | sed -n "s/^Simple mixer control '\(.*\)',[0-9]*$/\1/p" \
        | while IFS= read -r ctl; do
            caps=$(amixer -c "$card" sget "$ctl" 2>/dev/null \
                | sed -n 's/^  Capabilities: //p')
            case " $caps " in
                *volume*)
                    amixer -c "$card" sset "$ctl" 100% >/dev/null 2>&1 || true
                    amixer -c "$card" sset "$ctl" unmute >/dev/null 2>&1 || true
                    ;;
            esac
        done
}

# --- 1. Wait for a USB audio card ------------------------------------------
CARD=""
for _ in $(seq 1 30); do
    CARD=$(usb_card_name)
    [ -n "$CARD" ] && break
    sleep 1
done
if [ -z "$CARD" ]; then
    log "no USB audio card found after 30s — nothing to do"
    exit 0
fi
log "USB audio card: $CARD"

# --- 2. Card profile --------------------------------------------------------
if [ "${1:-}" = "--select-profile" ]; then
    PROFILE=$(choose_profile "$(card_profiles "$CARD")" || true)
    if [ -n "${PROFILE:-}" ]; then
        log "selected profile: $PROFILE"
        pactl set-card-profile "$CARD" "$PROFILE" 2>/dev/null || true
        write_state_profile "$CARD" "$PROFILE"
    else
        log "WARNING: no usable output+input profile found for $CARD"
    fi
    exit 0
fi

EXISTING=$(grep -s "^${CARD}=" "$STATE_FILE" | head -1 | cut -d= -f2-)
if [ -n "$EXISTING" ]; then
    log "respecting persisted profile: $EXISTING"
    pactl set-card-profile "$CARD" "$EXISTING" 2>/dev/null || true
else
    PROFILE=$(choose_profile "$(card_profiles "$CARD")" || true)
    if [ -n "${PROFILE:-}" ]; then
        log "no persisted profile — selecting: $PROFILE"
        pactl set-card-profile "$CARD" "$PROFILE" 2>/dev/null || true
        write_state_profile "$CARD" "$PROFILE"
    fi
fi

# --- 3. Poll for the source node --------------------------------------------
# Bluetooth-dongle devices (Yealink BT51) can take 1-4 min to re-establish
# their radio link after a reboot; WirePlumber only creates the nodes once the
# ALSA device is ready, so restart WirePlumber between attempts.
SOURCE=""
for attempt in 0 1 2 3; do
    if [ "$attempt" -gt 0 ]; then
        log "source not up yet — restarting WirePlumber (attempt $attempt/3)"
        systemctl --user restart wireplumber
        sleep 5
    fi
    for _ in $(seq 1 55); do
        SOURCE=$(usb_source_name)
        [ -n "$SOURCE" ] && break 2
        sleep 1
    done
done
[ -n "$SOURCE" ] && log "USB source: $SOURCE" || log "WARNING: USB source never appeared"

# --- 4. Force default routing -----------------------------------------------
SINK=$(usb_sink_name)
if [ -n "$SINK" ]; then
    pw-metadata -n default 0 default.configured.audio.sink \
        "{\"name\":\"$SINK\"}" 'Spa:String:JSON' >/dev/null 2>&1 || true
fi
if [ -n "$SOURCE" ]; then
    pw-metadata -n default 0 default.configured.audio.source \
        "{\"name\":\"$SOURCE\"}" 'Spa:String:JSON' >/dev/null 2>&1 || true
fi

# --- 5. Restore hardware mixer levels for 20 s -------------------------------
# WirePlumber's late ACP profile reset silently mutes hardware volume a few
# seconds after the device appears — keep re-applying to catch it.
for _ in $(seq 1 10); do
    CARD_NUM=$(usb_alsa_card_num || true)
    [ -n "${CARD_NUM:-}" ] && unmute_all_controls "$CARD_NUM"
    [ -n "$SOURCE" ] && pactl set-source-volume "$SOURCE" 100% 2>/dev/null || true
    sleep 2
done
log "done"
