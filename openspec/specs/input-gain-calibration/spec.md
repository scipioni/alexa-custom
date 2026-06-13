# Spec: Input Gain Calibration

## Purpose

Provides an automatic microphone input gain calibration routine that the user can trigger via a voice command. The action probes a set of candidate gain values, scores each by STT transcript similarity, and persists the best gain so the daemon uses it on subsequent startups.

## Requirements

### Requirement: calibrate_input_gain action registration
The system SHALL register a `calibrate_input_gain` action type in the action registry, callable from `conf/actions/user.yaml` like any other action.

#### Scenario: Action fires from config
- **WHEN** a trigger fires with `type: calibrate_input_gain`
- **THEN** the calibration loop starts

### Requirement: Adaptive 5-probe gain search
The action SHALL probe 5 distinct gain values across two rounds. Round 1 tests `gain_low`, `gain_mid`, and `gain_high` (configurable via params, defaults 0.4 / 0.7 / 1.2). Round 2 tests two values in the half-interval around the Round 1 winner: `[winner - half_step, winner + half_step]` where `half_step = (gain_high - gain_low) / 6`.

#### Scenario: Round 1 winner is mid, round 2 zooms in
- **WHEN** Round 1 scores peak at `gain_mid`
- **THEN** Round 2 probes `[gain_mid - half_step, gain_mid + half_step]`

#### Scenario: Tie broken by lower gain
- **WHEN** two gain values produce equal similarity scores
- **THEN** the lower gain value is selected as winner

### Requirement: Per-probe TTS announcement
Before each recording attempt the system SHALL speak "prova N di 5: <sentence>" (where N is 1–5 and sentence is the calibration phrase) via the TTS engine.

#### Scenario: Probe 3 announcement
- **WHEN** the third probe starts
- **THEN** TTS speaks "prova 3 di 5: <sentence>" before recording begins

### Requirement: Gain settle delay
The system SHALL wait `settle_ms` milliseconds (default 500) after calling `set_input_gain()` before starting TTS and recording for that probe.

#### Scenario: Default settle delay
- **WHEN** `settle_ms` param is not specified
- **THEN** the system waits 500 ms after each gain change

### Requirement: STT-based scoring
Each probe SHALL be scored by computing `get_similarity_score(transcript, sentence, "levenshtein")`. A probe that times out with no transcript scores 0.

#### Scenario: Empty transcript
- **WHEN** `listen_fn` returns an empty string or None for a probe
- **THEN** that probe's score is 0.0

### Requirement: Best gain applied and persisted
After all 5 probes the system SHALL call `set_input_gain()` with the winning gain and persist it to `conf/state.yaml` via `save_input_gain_config()`.

#### Scenario: Successful calibration persisted
- **WHEN** calibration completes with a clear winner
- **THEN** `conf/state.yaml` contains `input_gain: <winning_value>` and `get_input_gain()` returns the winning value

### Requirement: Completion announcement
The system SHALL speak a completion message (e.g. "Calibrazione completata. Guadagno impostato a X percento") after saving the winning gain.

#### Scenario: Completion message spoken
- **WHEN** calibration loop finishes
- **THEN** TTS speaks the result before the action returns

### Requirement: Configurable params
The action SHALL accept the following optional params with documented defaults:

| param | default | description |
|---|---|---|
| `sentence` | `"uno due tre quattro cinque"` | Phrase the user repeats |
| `gain_low` | `0.4` | Lower bound of probe range |
| `gain_mid` | `0.7` | Middle probe value |
| `gain_high` | `1.2` | Upper bound of probe range |
| `listen_timeout` | `6.0` | Seconds to wait for user speech per probe |
| `settle_ms` | `500` | Milliseconds to wait after gain change |

#### Scenario: Custom sentence via params
- **WHEN** action params include `sentence: "sei sette otto nove dieci"`
- **THEN** all five TTS announcements use that sentence and scoring compares against it

### Requirement: listen_fn unavailable guard
When `listen_fn` is `None` the action SHALL log a warning and return immediately without running any probes.

#### Scenario: No listen_fn
- **WHEN** `listen_fn` is None at action dispatch time
- **THEN** a warning is logged and the action returns without calling TTS or changing gain

### Requirement: Calibrated gain loaded at startup
The system SHALL load `input_gain` from `conf/state.yaml` at daemon startup (via `load_input_gain_state()`). If present, this value SHALL override `config.yaml`'s `audio.input_gain`.

#### Scenario: State file present at startup
- **WHEN** `conf/state.yaml` contains `input_gain: 0.85`
- **THEN** the daemon initialises with `input_gain = 0.85` regardless of `config.yaml`
