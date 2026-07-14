## 1. CSS Variable Cleanup

- [x] 1.1 Add `--bar-bg: rgba(0,0,0,0.3)` to the existing `:root` block
- [x] 1.2 Add `--transcribing: #94a3b8` to the existing `:root` block
- [x] 1.3 Add `--reply-trig: #86efac` to the existing `:root` block
- [x] 1.4 Replace hardcoded `rgba(0,0,0,0.3)` in `#status-bar` background CSS with `var(--bar-bg)`
- [x] 1.5 Replace hardcoded `#94a3b8` inline style in `setStt` JS with `var(--transcribing)` (use CSS class or inline `var()`)
- [x] 1.6 Replace hardcoded `#86efac` inline style in `renderActions` JS with `var(--reply-trig)`

## 2. Light Theme CSS

- [x] 2.1 Add `[data-theme="light"]` block after `:root` overriding: `--bg`, `--surface`, `--border`, `--text`, `--bar-bg`, `--transcribing`, `--reply-trig`
- [x] 2.2 Verify scrollbar thumb and all `backdrop-filter` surfaces look correct in light mode

## 3. Theme-Init Script (anti-flash)

- [x] 3.1 Add inline `<script>` in `<head>` (before `</head>`) that reads `localStorage.getItem('theme')` or `matchMedia('(prefers-color-scheme: light)')` and sets `document.documentElement.setAttribute('data-theme', …)` synchronously
- [x] 3.2 Add `matchMedia` change listener that updates theme only when no localStorage override is present

## 4. Toggle Button

- [x] 4.1 Add `<button id="btn-theme" aria-label="Toggle theme">☀</button>` to the status bar HTML, after `#ws-ind`
- [x] 4.2 Style `#btn-theme` consistently with the existing `panel-hdr button` style (no border, muted color, hover effect)
- [x] 4.3 Implement `toggleTheme()` JS function: flip `data-theme` on `<html>`, save to `localStorage`, update button icon
- [x] 4.4 Wire `onclick="toggleTheme()"` to `#btn-theme`
- [x] 4.5 Ensure button icon initialises correctly on page load (☀ in dark, 🌙 in light)
