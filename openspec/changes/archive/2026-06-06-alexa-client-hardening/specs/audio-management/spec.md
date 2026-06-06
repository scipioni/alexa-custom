## MODIFIED Requirements

### Requirement: Proactive PipeWire state enforcement
The system SHALL run a background daemon thread that monitors PipeWire events and ensures that the configured audio hardware is correctly initialized and routed. The target audio card name SHALL be sourced from `config.audio_card_name` (default `"NewPie"`) rather than being hardcoded. A `configure(cfg)` function SHALL be provided to update the module-level audio parameters after each config load or hot-reload.

#### Scenario: Device profile enforced on connect
- **WHEN** a configured Bluetooth device connects in A2DP mode
- **THEN** the system automatically switches it to the `headset-head-unit` (mSBC) profile to enable the microphone

#### Scenario: Default routing snatched back
- **WHEN** another audio device (e.g., HDMI) becomes the default PipeWire sink while the configured device is connected
- **THEN** the system automatically snatches back the default status for the configured device

#### Scenario: Custom audio_card_name used for device search
- **WHEN** `config.yaml` sets `audio_card_name: ConferenceCam` and `audio.configure(cfg)` is called
- **THEN** `find_alexa_card()` matches cards containing `conferencecam` (case-insensitive) instead of `newpie`

### Requirement: Adaptive session sample rates
The system SHALL detect the connection type of the active audio device and adjust the LiveKit session parameters accordingly. Sample rates SHALL be sourced from `config.audio_sample_rates` (with defaults `usb: 48000`, `bluetooth: 16000`, `internal: 48000`) rather than hardcoded constants.

#### Scenario: Bluetooth sample rate optimization
- **WHEN** the active audio device is detected as Bluetooth
- **THEN** the LiveKit session sample rate is set to the configured `audio_sample_rates.bluetooth` value (default 16000 Hz)

#### Scenario: Custom USB sample rate
- **WHEN** `config.yaml` sets `audio_sample_rates: {usb: 44100}`
- **THEN** the LiveKit session sample rate for a USB device is 44100 Hz
