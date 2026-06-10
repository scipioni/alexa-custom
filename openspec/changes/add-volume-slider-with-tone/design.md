## Context

The alexa-custom project runs a web dashboard for monitoring and controlling the smart assistant. Volume control currently exists only through:
- `config.yaml` configuration file (requires daemon restart to apply changes)
- Direct shell commands (`wpctl set-volume`)
- Command-line tools

The web dashboard lacks interactive volume adjustment, making it difficult to adjust volume during live use. Users also need audible feedback to verify volume levels, similar to Windows volume mixer behavior.

## Goals / Non-Goals

**Goals:**
- Add interactive volume slider to web dashboard monitoring section
- Support 0-100% volume range with visual percentage display
- Play test tone on slider release (mouseup) for audible confirmation
- Persist volume changes to config.yaml
- Integrate seamlessly with existing audio control infrastructure

**Non-Goals:**
- Real-time volume visualization (VU meter style) — only control, not display
- Input gain control via web UI
- Volume control during active livekit calls (already handled by underlying system)
- Volume presets or quick-select buttons beyond the slider
- Continuous tone during dragging (only on release)

## Decisions

### 1. Tone Behavior: Play on Mouseup Only
**Decision**: Play tone when user releases the slider (mouseup), not while dragging.

**Rationale**:
- Prevents audio feedback loops or annoyance during drag operations
- Matches user expectation (Windows-style behavior)
- Reduces system load (no need to play tone on every movement event)

**Alternatives Considered**:
- Continuous tone during drag: Would provide real-time feedback but could become annoying
- Play tone on input (mousedown): Too sensitive, plays on every click
- Play tone on threshold (e.g., every 10%): More control but adds UI complexity

### 2. Tone Frequency Scales with Volume
**Decision**: Use different frequencies based on volume level:
- 330Hz (E4) for low volume (<30%)
- 440Hz (A4) for medium volume (30-70%)
- 523Hz (C5) for high volume (>70%)

**Rationale**:
- Provides intuitive feedback: higher pitch = louder
- Pleasant tones that aren't jarring
- Easy to distinguish between volume levels

**Alternatives Considered**:
- Fixed frequency (e.g., 440Hz): Doesn't communicate volume level
- Random frequency: No correlation with volume
- No tone: User requested this feature specifically

### 3. Slider Placement: Separate Row Below VU Meters
**Decision**: Place volume slider in a new row below VU meters in the monitoring section.

**Rationale**:
- Clear separation between display (VU meters) and control (slider)
- Consistent with existing layout patterns in the dashboard
- Easy to discover for users
- Doesn't clutter VU meter area

**Alternatives Considered**:
- Integrated into VU meter row: Would be compact but potentially confusing
- Separate small panel: Would require more space and could feel disconnected
- Floating overlay: Too intrusive and interrupts workflow

### 4. Web Control via WebSocket Control Actions
**Decision**: Use existing WebSocket control infrastructure (`_handle_control()`) to send `set_volume` and `beep` actions.

**Rationale**:
- Leverages existing WebSocket pattern already in use (e.g., `restart` action)
- No need to create new WebSocket message types or protocols
- Simple client-server communication
- Consistent with existing architecture

**Alternatives Considered**:
- New WebSocket endpoint (e.g., `/api/volume`): Would require additional routing
- Direct HTTP POST to backend: Would require authentication and different flow
- Browser-native API (Web Audio): Complex to integrate with existing audio pipeline

### 5. Direct Volume Setter Without pulsectl
**Decision**: Create `set_output_volume_direct()` in `audio_ops.py` that directly calls `wpctl` without requiring `pulsectl.Pulse()` connection.

**Rationale**:
- Per AGENTS.md guidelines, opening `pulsectl.Pulse()` triggers ALSA device reinitialization, resetting PCM to 0%
- The `_restore_hw_pcm()` function already handles this cleanup
- Direct `wpctl` call is sufficient for volume changes

**Alternatives Considered**:
- Use existing `set_output_volume()` from audio_hw.py: Requires pulsectl connection, triggers PCM reset
- Create global pulsectl connection in WebServer: Would need to manage lifecycle and still triggers PCM reset
- Use `wpctl` via subprocess (chosen): Simple, non-blocking, doesn't require pulse connection

## Risks / Trade-offs

**[Risk] wpctl calls may fail silently**
- **Mitigation**: Capture subprocess output and log warnings/errors; volume change still persists in `_OUTPUT_VOLUME` module variable

**[Risk] Tone may play too quietly for some users**
- **Mitigation**: Use volume 0.6 in `play_beep()`; user can increase system volume independently

**[Risk] Volume setting may not persist across daemon restarts**
- **Mitigation**: `save_volume_config()` already writes to `config.yaml`; daemon reads this on startup

**[Risk] Browser compatibility for range input styling**
- **Mitigation**: Use standard CSS with vendor prefixes; degrade gracefully on older browsers

**[Trade-off] Volume control is server-side**
- **Benefit**: Consistent with existing architecture; leverages existing audio infrastructure
- **Limitation**: Cannot control volume per-client; affects all dashboard users equally
- **Impact**: Acceptable since this is a single-user dashboard

## Migration Plan

1. **Development**: Implement new features in existing codebase
2. **Testing**: Test volume slider toggling, tone playback, volume persistence
3. **Deployment**: Restart alexa-client daemon to pick up changes
4. **Rollback**: If issues arise, revert code changes; volume will revert to config.yaml value

No database migrations or data format changes required.