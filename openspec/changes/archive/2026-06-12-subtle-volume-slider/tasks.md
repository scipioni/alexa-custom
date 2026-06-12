## 1. Track and thumb resize

- [x] 1.1 Reduce `#volume-slider` track height from 12px to 4px, adjust border-radius proportionally (2px)
- [x] 1.2 Reduce `#volume-slider::-webkit-slider-thumb` from 24px to 14px, remove `box-shadow`, remove `border`, remove hover/active `transform`
- [x] 1.3 Reduce `#volume-slider::-moz-range-thumb` from 24px to 14px, remove `box-shadow`, remove `border`, remove hover/active `transform`
- [x] 1.4 Remove the `.dragging` CSS class block (lines 1001–1004 and 1015–1018)
- [x] 1.5 Remove `transition` properties on thumb and slider (box-shadow, transform transitions)

## 2. Color scheme simplification

- [x] 2.1 Replace the three-color `_setSliderFill()` gradient with a single muted accent color (e.g., `var(--info)` with 0.6–0.7 opacity, or a new `--volume-fill` variable)
- [x] 2.2 Update `#volume-slider` background `linear-gradient` to use the new single fill color for both track and thumb
- [x] 2.3 Verify no remaining references to `--match`, `--amber`, or `--nomatch` in the volume slider CSS or JS color logic

## 3. Hover and drag feedback removal

- [x] 3.1 Remove `#volume-slider::-webkit-slider-thumb:hover` scale and glow
- [x] 3.2 Remove `#volume-slider::-moz-range-thumb:hover` scale and glow
- [x] 3.3 Remove `#volume-slider.dragging::-webkit-slider-thumb` rules
- [x] 3.4 Remove `#volume-slider.dragging::-moz-range-thumb` rules
- [x] 3.5 Ensure `.dragging` class is no longer toggled in JS, or keep the JS toggle but make the CSS block empty (preferred: keep JS untouched, CSS empty)

## 4. Verify

- [x] 4.1 Open dashboard.html, visually confirm reduced track and thumb size
- [x] 4.2 Drag the slider — confirm percentage updates in real time and `set_volume` message fires on release
- [x] 4.3 Hover over thumb — confirm no scale or glow
- [x] 4.4 Confirm no CSS changes leaked to other dashboard elements
