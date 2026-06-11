## ADDED Requirements

### Requirement: Digital gain applied in _play_array

`_play_array()` SHALL scale float32 audio samples by `get_output_volume()` before converting to int16 and writing the WAV file.

#### Scenario: Volume at 50% produces half-amplitude WAV

- **WHEN** `_play_array()` is called with a float32 sine wave at amplitude 1.0 and `get_output_volume()` returns 0.5
- **THEN** the int16 WAV samples SHALL have amplitude ~16384 (±1), not ~32767
- **AND** the WAV SHALL play correctly through `pw-play`

#### Scenario: Volume at 100% produces full-amplitude WAV

- **WHEN** `_play_array()` is called with `get_output_volume()` returning 1.0
- **THEN** the int16 WAV samples SHALL match the current (pre-change) behavior at full amplitude

#### Scenario: Volume at 0% produces silence

- **WHEN** `_play_array()` is called with `get_output_volume()` returning 0.0
- **THEN** the resulting WAV SHALL contain only silence (all zero samples)

### Requirement: Digital gain applied in _play_raw

`_play_raw()` SHALL scale float32 samples decoded from the byte buffer by `get_output_volume()` before int16 conversion, following the same pattern as `_play_array`.

#### Scenario: _play_raw scaling matches _play_array

- **WHEN** `_play_raw()` and `_play_array()` both receive equivalent audio at the same output volume
- **THEN** the resulting int16 PCM data SHALL be identical

### Requirement: Digital gain applied in Piper streaming

`PiperTTS._say_streaming()` SHALL scale int16 audio chunks by `get_output_volume()` before writing to the `paplay` stdin pipe.

#### Scenario: Piper streaming at reduced volume

- **WHEN** Piper TTS streams audio at `get_output_volume()` = 0.3
- **THEN** each chunk SHALL have its int16 samples multiplied by 0.3 (as float, then back to int16) before `proc.stdin.write()`
- **AND** the streaming path SHALL NOT introduce audible artifacts beyond expected quantization

### Requirement: wpctl set-volume uses unity gain

`set_output_volume()` SHALL call `wpctl set-volume @DEFAULT_AUDIO_SINK@` with value `1.0` regardless of the requested volume, to prevent double-attenuation with the new digital gain.

#### Scenario: wpctl always sets unity

- **WHEN** `set_output_volume()` is called with any volume value (e.g., 0.3, 0.7, 1.0)
- **THEN** the subprocess argument SHALL be `"1.0"`, not the requested volume

### Requirement: _restore_hw_pcm preserved

`_restore_hw_pcm()` SHALL continue to run after the wpctl call in `set_output_volume()` to maintain PCM hardware volume at 100% despite the PipeWire ALSA re-init bug.

#### Scenario: PCM restored after set-volume

- **WHEN** `set_output_volume()` completes
- **THEN** `amixer -c 0 sset PCM 100%` SHALL have been called (asserted via existing `_restore_hw_pcm` hook)
