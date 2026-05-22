# Tasks: Gated STT during calls

- [x] **Research and Validation**
    - [x] Verify `livekit_connected_flag` access in both STT loop functions.
    - [x] Check `vosk.KaldiRecognizer.Reset()` availability in current version.

- [x] **Implementation - STT Logic**
    - [x] Add `_STT_COOLDOWN` constant to `stt.py`.
    - [x] Implement gating/cooldown in `_single_stage_loop`.
    - [x] Implement gating/cooldown in `_recognition_loop`.
    - [x] Ensure RMS level is still calculated and emitted during gating (so VU meters work).

- [x] **Implementation - TUI**
    - [x] Add `gated` state to `STTStatus` widget in `tui.py`.
    - [x] Update `_handle_stt_event` to process the `gated` event.
    - [x] Verify visual feedback in TUI.

- [x] **Verification**
    - [x] Start a call and verify that wake words are ignored.
    - [x] End a call and verify that STT resumes after ~1s.
    - [x] Monitor CPU usage during a call to confirm drop in Vosk activity.
