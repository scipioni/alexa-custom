#!/usr/bin/env python3
import sys
import sounddevice as sd
import numpy as np
import pulsectl


def find_pipewire_device():
    """Return the sounddevice index for the PipeWire ALSA device."""
    return next(
        (i for i, d in enumerate(sd.query_devices()) if d['name'] == 'pipewire'),
        None,
    )


def find_newpie_card(pulse):
    """Return the pulsectl card object for the NewPie, or None."""
    for card in pulse.card_list():
        if 'NewPie' in card.proplist.get('device.description', ''):
            return card
    return None


def check_newpie_ready():
    """
    Verify NewPie is connected and on the headset-head-unit (mSBC) profile.
    Prints warnings and returns False if anything is wrong.
    """
    ok = True
    with pulsectl.Pulse('newpie-check') as pulse:
        card = find_newpie_card(pulse)
        if card is None:
            print("ERROR: NewPie not found. Is it paired and connected?")
            print("  bluetoothctl connect 28:36:38:3E:59:D0")
            return False

        profile = card.profile_active.name if card.profile_active else 'off'
        if profile != 'headset-head-unit':
            print(f"WARNING: NewPie profile is '{profile}', expected 'headset-head-unit'")
            print("  Fix: pactl set-card-profile bluez_card.28_36_38_3E_59_D0 headset-head-unit")
            ok = False

        info = pulse.server_info()
        sinks = {s.name: s for s in pulse.sink_list()}
        sources = {s.name: s for s in pulse.source_list()}

        default_sink = sinks.get(info.default_sink_name)
        default_source = sources.get(info.default_source_name)

        if default_sink is None or 'NewPie' not in default_sink.description:
            print(f"WARNING: Default sink is not NewPie (got: {info.default_sink_name})")
            print("  Fix: wpctl set-default <newpie-sink-id>")
            ok = False

        if default_source is None or 'NewPie' not in default_source.description:
            print(f"WARNING: Default source is not NewPie (got: {info.default_source_name})")
            print("  Fix: wpctl set-default <newpie-source-id>")
            ok = False

    return ok


def list_devices():
    print("=" * 60)
    print("BLUETOOTH / AUDIO DEVICES")
    print("=" * 60)

    with pulsectl.Pulse('newpie-lister') as pulse:
        info = pulse.server_info()

        cards = pulse.card_list()
        if cards:
            print("\n[Cards]")
            for card in cards:
                desc = card.proplist.get('device.description', card.name)
                profile = card.profile_active.name if card.profile_active else 'off'
                print(f"  {card.index}: {desc}")
                print(f"      Name:    {card.name}")
                print(f"      Profile: {profile}")

        print("\n[Sinks - Output]")
        for sink in pulse.sink_list():
            marker = " [DEFAULT]" if sink.name == info.default_sink_name else ""
            print(f"  {sink.index}: {sink.description}{marker}")
            print(f"      Name: {sink.name}")

        print("\n[Sources - Input]")
        for source in pulse.source_list():
            if 'monitor' not in source.name:
                marker = " [DEFAULT]" if source.name == info.default_source_name else ""
                print(f"  {source.index}: {source.description}{marker}")
                print(f"      Name: {source.name}")

    print("\n" + "=" * 60)
    print("Sounddevice / ALSA Devices")
    print("=" * 60)
    for i, device in enumerate(sd.query_devices()):
        print(f"  {i}: {device['name']}")
        print(f"      In: {device['max_input_channels']} ch, Out: {device['max_output_channels']} ch")


def speakerphone():
    print("=" * 60)
    print("NewPie Bluetooth Conference Speakerphone")
    print("=" * 60)

    if not check_newpie_ready():
        sys.exit(1)

    pw_device = find_pipewire_device()
    if pw_device is None:
        print("ERROR: PipeWire ALSA device not found. Is PipeWire running?")
        sys.exit(1)

    print(f"\nPipeWire device index: {pw_device}")
    print("Starting loopback (mic → speaker). Press Ctrl+C to stop.\n")

    frame_count = 0

    def audio_callback(indata, outdata, frames, time, status):
        nonlocal frame_count
        if status:
            print(f"Audio status: {status}", file=sys.stderr)
        outdata[:] = indata
        frame_count += frames
        if frame_count % 16000 == 0:
            print(f"  {frame_count // 16000}s", flush=True)

    try:
        with sd.Stream(
            device=pw_device,
            samplerate=16000,
            blocksize=1024,
            channels=1,
            dtype=np.float32,
            callback=audio_callback,
        ):
            while True:
                sd.sleep(500)
    except KeyboardInterrupt:
        print(f"\nStopped after {frame_count // 16000}s ({frame_count} frames).")
    except sd.PortAudioError as e:
        print(f"\nAudio error: {e}")
        print("Is the NewPie still connected?")
        sys.exit(1)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ('--list', '-l', 'list'):
        list_devices()
    else:
        speakerphone()


if __name__ == '__main__':
    main()
