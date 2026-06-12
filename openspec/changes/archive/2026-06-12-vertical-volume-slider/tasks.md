## 1. HTML Restructure

- [x] 1.1 Move the volume slider `<input>` and its percent label into the SPK `.vu-row-v`, creating a second flex column to the right of the VU bar
- [x] 1.2 Remove the standalone `<div id="volume-control">` row from below the VU block
- [x] 1.3 Add a `VOLUME` label above the vertical slider (matching the `vu-lbl-v` pattern)

## 2. CSS — Vertical Slider

- [x] 2.1 Add styles for the vertical slider: `writing-mode: vertical-lr; direction: rtl; height: 160px; width: 30px;`
- [x] 2.2 Remove or update the horizontal `width: 100%` on `#volume-slider` — the slider track now needs a fixed height, not width
- [x] 2.3 Update `#volume-slider::-webkit-slider-thumb` and `::-moz-range-thumb` for the vertical orientation (adjust sizing if needed)
- [x] 2.4 Remove the `border-top` and `margin-top/padding` from the old `#volume-control` block since it no longer exists

## 3. CSS — SPK Column Layout

- [x] 3.1 Add `.spk-bars` flex row inside the SPK column to hold VU bar and vertical slider side-by-side
- [x] 3.2 Set gap between VU bar and slider (`gap: 8px`)

## 4. JS — Fill Gradient

- [x] 4.1 Update `_setSliderFill()` to work with vertical orientation — simplified to just set `--vol-color` for thumb/glow, removed `--vol-pct` gradient fill
- [x] 4.2 Verify `initVolumeSlider()` still works — the `oninput` and `onmouseup` handlers are orientation-agnostic

## 5. Verification

- [ ] 5.1 Load dashboard and confirm vertical slider renders at correct height/position
- [ ] 5.2 Drag slider up and down — confirm percentage updates in real-time
- [ ] 5.3 Release slider — confirm beep plays at correct pitch for volume level
- [ ] 5.4 Verify external volume sync (system_stats message) updates the slider position
- [ ] 5.5 Confirm no standalone volume-control row remains below the VU block
- [ ] 5.6 Verify MIC column is unaffected
