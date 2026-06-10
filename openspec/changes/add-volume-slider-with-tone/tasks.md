## 1. Backend Volume Control

- [x] 1.1 Add `set_output_volume_direct()` function to `alexa_custom/audio_ops.py`
- [x] 1.2 Export `set_output_volume_direct()` in `alexa_custom/audio_ops.py` `__all__` (not applicable - no __all__ list exists)
- [x] 1.3 Add `set_volume` action handler to `WebServer._handle_control()` in `alexa_custom/web.py`
- [x] 1.4 Handle `beep` action in `WebServer._handle_control()` in `alexa_custom/web.py`
- [x] 1.5 Import `set_output_volume_direct()` and `play_beep()` in `web.py` (imported inside handlers)

## 2. Frontend Volume Slider UI

- [x] 2.1 Add volume slider HTML to `dashboard.html` in `vu-bottom` section
- [x] 2.2 Add CSS styling for volume slider in `dashboard.html`
- [x] 2.3 Add CSS styling for slider thumb in `dashboard.html`
- [x] 2.4 Add CSS styling for volume percentage display in `dashboard.html`

## 3. Frontend JavaScript Logic

- [x] 3.1 Add `initVolumeSlider()` function in `dashboard.html` JavaScript
- [x] 3.2 Add `playBeepForVolume()` helper function in `dashboard.html` JavaScript
- [x] 3.3 Add `set_volume` action handler in `dashboard.html` JavaScript
- [x] 3.4 Add `beep` action handler in `dashboard.html` JavaScript
- [x] 3.5 Call `initVolumeSlider()` on WebSocket hello message in `dashboard.html`
- [x] 3.6 Add event handlers for slider input (update percentage display)
- [x] 3.7 Add event handler for slider mouseup (send control and play tone)

## 4. Testing

- [ ] 4.1 Test volume slider displays current volume on page load
- [ ] 4.2 Test volume slider updates percentage display during drag
- [ ] 4.3 Test volume slider sets volume correctly on mouseup
- [ ] 4.4 Test tone plays at correct frequency for low volume (<30%)
- [ ] 4.5 Test tone plays at correct frequency for medium volume (30-70%)
- [ ] 4.6 Test tone plays at correct frequency for high volume (>70%)
- [ ] 4.7 Test no tone plays when volume is 0%
- [ ] 4.8 Test volume persists after daemon restart
- [ ] 4.9 Test volume changes work during active LiveKit call
- [ ] 4.10 Test volume control doesn't affect input gain