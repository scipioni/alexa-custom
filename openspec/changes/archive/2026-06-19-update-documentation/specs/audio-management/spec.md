# Capability: Audio Management

## MODIFIED Requirements

### Requirement: Proactive PipeWire state enforcement

The system SHALL run a background daemon thread (AudioWatcher) that monitors PipeWire events via pulsectl and ensures that the configured audio hardware is correctly initialized and routed. On every PulseAudio event (device connect/disconnect), AudioWatcher SHALL call `_check_and_enforce()` which re-applies the NewPie as the default sink/source and calls `_restore_hw_pcm()`.

#### Scenario: AudioWatcher restores PCM on event
- **WHEN** a PulseAudio event fires (e.g. HDMI connected)
- **THEN** AudioWatcher runs `_check_and_enforce()`
- **AND** `_restore_hw_pcm()` is called to reset the NewPie hardware PCM to 100%

#### Scenario: AudioWatcher started on daemon boot
- **WHEN** the daemon starts
- **THEN** AudioWatcher runs as a background thread
- **AND** it calls `_restore_hw_pcm()` on first event after opening the pulsectl connection

## ADDED Requirements

### Requirement: PCM restore after pulsectl

The system SHALL call `_restore_hw_pcm()` immediately after closing any `pulsectl.Pulse()` context, because pipewire-pulse reinitializes the ALSA device on pulsectl connect and resets the NewPie hardware PCM mixer to 0%.

#### Scenario: PCM restored after pulsectl
- **WHEN** any code opens a `pulsectl.Pulse()` context and then closes it
- **THEN** `_restore_hw_pcm()` is called
- **AND** the NewPie card's PCM mixer is set back to 100%

### Requirement: GStreamer capture profiles with STT overrides

The system SHALL support named GStreamer capture profiles under `audio.gstreamer.profiles`. Each profile SHALL be able to override GStreamer pipeline parameters AND STT parameters (rms_threshold, vad_silence_ms). The active profile SHALL be stored in `conf/state.yaml` and switchable at runtime.

#### Scenario: Profile switches GStreamer and STT params
- **WHEN** `set_audio_profile` action fires with `profile: sensitive`
- **THEN** the GStreamer pipeline restarts with `sensitive` profile's noise_suppression_level, agc_target_level_dbfs, agc_compression_gain_db
- **AND** the STT loop applies the profile's `rms_threshold` and `vad_silence_ms` overrides

### Requirement: Switch-on-connect module disabled

The system SHALL NOT use `libpipewire-module-switch-on-connect`. The `task audio:setup` task SHALL remove any stale drop-in config files.

#### Scenario: Stale drop-in removed
- **WHEN** `task audio:setup` runs
- **THEN** `~/.config/pipewire/pipewire.conf.d/99-switch-on-connect.conf` is deleted if present
- **AND** `~/.config/pipewire/pipewire-pulse.conf.d/99-switch-on-connect.conf` is deleted if present

### Requirement: USB autosuspend disabled via system service

The system SHALL disable USB autosuspend for the NewPie device via a systemd system service (`newpie-autosuspend.service`), not via udev rules (which cause boot crashes when the device is connected at power-on).

#### Scenario: Autosuspend service installed
- **WHEN** `task audio:setup` runs
- **THEN** `newpie-autosuspend.service` is installed in `/etc/systemd/system/`
- **AND** it is enabled and started

### Requirement: WirePlumber no-suspend config

The system SHALL install a WirePlumber drop-in config that keeps the NewPie source always active (prevents suspension for native PipeWire clients like pipewiresrc).

#### Scenario: WirePlumber config installed
- **WHEN** `task audio:setup` runs
- **THEN** `51-newpie-no-suspend.conf` is placed in `~/.config/wireplumber/wireplumber.conf.d/`
