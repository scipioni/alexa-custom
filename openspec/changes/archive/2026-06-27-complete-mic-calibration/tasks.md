## 1. Action Registration & Stage 1 Reuse

- [x] 1.1 Register the `calibrate_microphone_complete` action type in the action registry in `alexa_custom/actions.py`
- [x] 1.2 Route Stage 1 of the new action to execute the adaptive 5-probe gain calibration logic from `calibrate_input_gain`

## 2. GStreamer Filter Sweep Logic

- [x] 2.1 Implement Stage 2 of the action in `alexa_custom/actions.py` to prompt the user and sweep 3 GStreamer filter configurations
- [x] 2.2 Spin up isolated GStreamer capture subprocesses utilizing `start_capture_gst` and temporary overrides for each probe
- [x] 2.3 Compute Levenshtein similarity scores for each filter configuration probe and select the highest scoring combination

## 3. Configuration & State Persistence

- [x] 3.1 Add support for parsing and loading `gstreamer_override` from `conf/state.yaml` in `alexa_custom/audio_hw.py` and `alexa_custom/config.py`
- [x] 3.2 Save the winning Stage 2 parameters to `conf/state.yaml` and trigger a GStreamer capture pipeline restart to apply the updated configurations in real-time

## 4. Testing & Validation

- [x] 4.1 Write a new unit test suite in `tests/test_complete_calibration.py` to verify the dual-stage action execution and state file loading
- [x] 4.2 Run unit tests and manually verify the calibration command via voice triggers to confirm state.yaml updates
