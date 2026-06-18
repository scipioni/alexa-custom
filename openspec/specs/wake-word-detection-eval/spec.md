# Capability: Wake Word Detection Eval

## Purpose
Offline, microphone-free evaluation harness for the stage-1 wake-word detection pipeline. Measures false-positive and miss rates against labelled corpora so that backend and threshold choices can be made from data.

## Requirements

### Requirement: Offline microphone-free stage-1 evaluation
The system SHALL provide an evaluation harness that runs the stage-1 wake-detection pipeline against pre-recorded or synthesised audio clips without using a microphone or any PortAudio playback/capture path. The harness SHALL feed 16000 Hz, mono, s16le audio directly into the stage-1 backend in the same manner as live capture, and SHALL be runnable headless on a development host and on the target board.

#### Scenario: Harness scores a clip without a microphone
- **WHEN** the harness is run against a directory of labelled audio clips
- **THEN** each clip is fed through the configured stage-1 backend with no microphone or `sd.play`/`parec` capture, and a wake/no-wake decision is recorded per clip

#### Scenario: Harness honours audio constraints
- **WHEN** the harness runs on the target board
- **THEN** it does not open any PortAudio playback or capture stream and completes without blocking

### Requirement: Labelled positive and negative corpora
The harness SHALL operate over two labelled corpora: a **positive** corpus of clips that SHOULD trigger a wake, and a **negative** corpus of clips that SHALL NOT trigger a wake. The negative corpus SHALL be able to include Italian conversational speech, near-miss phrases (e.g. "Gabriele", "galleria", "assistenza"), background chatter, and gain-attenuated far-field/quiet variants. Positive clips SHALL be synthesisable from Piper TTS across multiple voices, speaking rates, and attenuation levels.

#### Scenario: Negative clip that triggers is a false positive
- **WHEN** a clip from the negative corpus produces a wake decision
- **THEN** the harness records it as a false positive and attributes it to the originating clip

#### Scenario: Positive clip that does not trigger is a miss
- **WHEN** a clip from the positive corpus does not produce a wake decision
- **THEN** the harness records it as a miss

#### Scenario: Corpus synthesised from Piper
- **WHEN** the corpus is (re)generated
- **THEN** positive clips for the configured wake words are synthesised using Piper voices already available to the project, at configurable speed and attenuation

### Requirement: False-positive and miss-rate reporting
The harness SHALL report, for a given configuration, the **false-positives-per-hour** (false wakes divided by total negative-corpus audio duration) and the **miss-rate** (missed positives divided by total positive clips). The report SHALL be deterministic for a fixed corpus and configuration.

#### Scenario: Metrics reported for a configuration
- **WHEN** the harness finishes a run for one backend/threshold configuration
- **THEN** it prints false-positives-per-hour and miss-rate, along with the counts and total negative-audio duration used to compute them

#### Scenario: Deterministic results
- **WHEN** the harness is run twice on the same corpus with the same configuration
- **THEN** the reported false-positive count, miss count, and rates are identical

### Requirement: Configuration sweep for comparison
The harness SHALL support sweeping across configurations — at minimum the acceptance threshold/confidence, and the Vosk confidence mode — and SHALL emit a comparison table of false-positives-per-hour versus miss-rate per configuration so that threshold choices can be made from data.

#### Scenario: Sweep produces a comparison table
- **WHEN** the harness is run with a sweep over threshold values
- **THEN** it emits one row per configuration showing the configuration and its false-positives-per-hour and miss-rate

### Requirement: Regression guard
The harness SHALL be runnable as a repeatable check (CLI entry point and/or test skill) so that a configuration or code change which increases false-positives-per-hour or miss-rate beyond a recorded baseline can be detected.

#### Scenario: Baseline regression detected
- **WHEN** the harness is run after a change and false-positives-per-hour exceeds the recorded baseline for the same corpus and configuration
- **THEN** the run surfaces the regression (non-zero exit or clearly flagged output)
