# Capability: Single Model STT

## MODIFIED Requirements

### Requirement: Configurable transcription backend

**MODIFIED**: The backend now also supports `capture_backend` (parec | gstreamer) with optional GStreamer webrtcdsp pipeline for noise suppression, AGC, high-pass filter, and compressor.

#### Scenario: GStreamer capture backend
- **WHEN** `stt.capture_backend` is `gstreamer`
- **THEN** the capture pipeline routes mic audio through a GStreamer pipeline with webrtcdsp before Vosk receives it
- **AND** the pipeline is configured under `audio.gstreamer.*`

#### Scenario: parec capture backend (default)
- **WHEN** `stt.capture_backend` is `parec` (or absent)
- **THEN** mic capture uses the traditional `parec` process with raw s16le 16 kHz stereo output to stdout

### Requirement: Audio capture profiles with runtime switching

The system SHALL support named audio capture profiles under `audio.gstreamer.profiles` that can override GStreamer pipeline parameters AND STT parameters (`rms_threshold`, `vad_silence_ms`). Profiles SHALL be switchable at runtime via the `set_audio_profile` action type.

#### Scenario: Profile switching via voice command
- **WHEN** a trigger with `type: set_audio_profile, profile: sensitive` fires
- **THEN** the GStreamer pipeline restarts with the `sensitive` profile's parameters
- **AND** the STT recognition loop applies the profile's `rms_threshold` and `vad_silence_ms` overrides

#### Scenario: Invalid profile falls back to base
- **WHEN** a profile name does not exist in `audio.gstreamer.profiles`
- **THEN** the base GStreamer config is used without crashing

### Requirement: Sleeping mode (stop_listening / start_listening)

The system SHALL support a sleeping mode where STT stops recognizing and the assistant ignores all wake words. The `stop_listening` action SHALL enter sleeping mode; `start_listening` SHALL exit it. Wake-up phrases SHALL be configurable as triggers with `type: start_listening` and `with_wake: false`.

#### Scenario: Stop listening action
- **WHEN** a `stop_listening` action fires
- **THEN** the STT loop enters sleeping state
- **AND** an event `sleeping` is emitted with the available wake-up phrases

#### Scenario: Start listening action
- **WHEN** a `start_listening` action fires
- **THEN** the STT loop exits sleeping state
- **AND** an event `listening` is emitted

### Requirement: Follow-up conversation mode

The system SHALL support a follow-up conversation mode where, after a matched command, the listening window re-opens without requiring a wake word, for up to `follow_up_max_turns` turns or until silence timeout.

#### Scenario: Follow-up enabled globally
- **WHEN** `recognition.follow_up: true` and a command matches
- **THEN** after dispatch, the system re-opens the listening window without requiring a new wake word
- **AND** the window closes after `recognition.follow_up_timeout` seconds of silence
- **AND** the window closes after `recognition.follow_up_max_turns` consecutive turns

#### Scenario: Follow-up disabled per trigger
- **WHEN** a trigger has `follow_up: false` and fires
- **THEN** no follow-up window opens, regardless of the global setting

## ADDED Requirements

### Requirement: Italian phonetic normalization for matching

The system SHALL normalize Italian text to a phonetic representation before fuzzy matching, handling geminate consonants, digraphs (gli, gn, sc, ch, gh), and trigraphs (sci, sce).

#### Scenario: Phonetic normalization applied
- **WHEN** the transcript contains "galileo" and the trigger phrase is "galileo"
- **THEN** `italian_phonetic()` reduces both to equivalent forms before comparison

### Requirement: Word-glob pattern matching

Triggers SHALL support word-glob patterns that are tested before fuzzy phonetic scoring. A pattern match SHALL be definitive — it selects the trigger immediately without scoring.

#### Scenario: Glob pattern matches
- **WHEN** a trigger has `patterns: ["accend* * luc*"]` and the transcript is "accendi le luci del salotto"
- **THEN** the trigger matches immediately via pattern, before fuzzy scoring runs
