## 1. Backend: Sync WebServer._output_volume

- [x] 1.1 In `web.py` `_handle_control` for `set_volume`, add `self._output_volume = volume` after calling `set_output_volume_direct(volume)`
- [x] 1.2 In `web.py` `_system_stats_loop`, import and call `get_output_volume()` from `alexa_custom.audio_hw`, add `output_volume` to the broadcast dict

## 2. Frontend: Volume slider CSS redesign

- [x] 2.1 Increase track height to 12px, add gradient fill via `background: linear-gradient(to right, <color> var(--vol-pct), var(--bar-bg) var(--vol-pct))` with dynamic color based on volume thresholds
- [x] 2.2 Enlarge thumb to 24px with 2px border matching fill color, strong box-shadow glow that intensifies at higher volumes
- [x] 2.3 Add hover (scale 1.15) and active (scale 1.3, max glow) states for the thumb
- [x] 2.4 Increase `#volume-control` padding and min-height to accommodate larger thumb
- [x] 2.5 Update JS `initVolumeSlider` and `oninput` handler to set `--vol-pct` CSS variable on the slider element

## 3. Frontend: Bidirectional sync logic

- [x] 3.1 In `dashboard.html` JS, inside `case 'system_stats'`, compare `m.output_volume` against current slider value
- [x] 3.2 If they differ, update slider value and percentage display without calling `sendVolumeControl` or `playBeepForVolume`
- [x] 3.3 Add a guard variable or inline check to prevent feedback loop when slider is being actively dragged

## 4. Testing

- [x] 4.1 Test slider displays gradient fill and correct color at low (<70%), medium (70-85%), and high (>85%) volumes — manual, visual
- [x] 4.2 Test thumb scales on hover and active drag — manual, visual
- [x] 4.3 Test volume changed via voice action is reflected on dashboard within 3 seconds — manual on target
- [x] 4.4 Test volume changed via shell `wpctl` is reflected on dashboard within 3 seconds — manual on target
- [x] 4.5 Test external volume update does not trigger beep or set_volume — manual on target
- [x] 4.6 Test new browser tab receives correct volume in hello message after slider change — manual on target
- [x] 4.7 Test slider works correctly in both dark and light theme — manual, visual
- [x] 4.8 Test no regression: slider mouseup still sends set_volume and plays tone — manual on target
