# Bill of Materials

Optional hardware add-ons for the Serena voice assistant. The three Amazon.it
items are listed at their VAT-inclusive (IVA) price; the Seeed item is sold in
USD and converted to EUR with 22% Italian IVA applied (see [Notes](#notes)).

All prices were captured on **2026-06-23** and may change.

---

## 1. reSpeaker XMOS XVF3800 — 4-Mic Array

**Link:** <https://www.seeed.cc/product/respeaker-mic-array-v2-0>
(shop SKU `100070894`: <https://www.seeedstudio.com/reSpeaker-Flex-XVF3800-Circular-4-with-XIAO-ESP32S3-p-6739.html>)

Professional circular 4-microphone array built on the **XMOS XVF3800**. It
performs on-board AI acoustic processing — AEC, multi-beamforming,
de-reverberation, Direction-of-Arrival (DoA), 60 dB AGC and dynamic noise
suppression — delivering clean far-field capture.

| Spec | Value |
|---|---|
| Microphones | 4× high-performance digital mics |
| Far-field pickup | 360°, up to 5 m |
| Max sample rate | 16 kHz |
| SNR / Sensitivity | 64 dBA / −26 dBFS |
| Interfaces | USB Audio Class 2.0 (plug-and-play) + I2S |
| Power | USB 5V |

**Role in Serena:** high-quality far-field voice-capture / wake-word input
(upgrade path over the basic USB speakerphone mic).

**Price:** **$51.43** (USD, Seeed Studio shop — SKU `100070894`, circular 4-mic
configuration) → approx **€57.73** incl. 22% IVA (see [Notes](#notes)).

---

## 2. Yealink SP92 — Conference Speakerphone

**Link:** <https://www.amazon.it/Yealink-SP92-Altoparlante-altoparlante-cancellazione/dp/B0FF9J4Z8D>

Portable USB + Bluetooth conference speaker with a built-in **AI
noise-cancelling microphone**. Full-duplex with acoustic echo cancellation,
50 mm speaker, 4 m voice sensing and Virtual Bass. ~20 h talk time, 276 g,
Microsoft Teams certified.

| Spec | Value |
|---|---|
| Connectivity | USB, Bluetooth (BT51-C), up to 30 m range |
| Speaker | 50 mm, 5 W, stereo |
| Battery | 20 h talk / 20 days standby |
| Pickup | full-duplex, AEC, AI noise cancellation |

**Role in Serena:** the project's USB "speakerphone" — combined speaker + mic.

**Price:** **€69.99** (incl. IVA, Amazon.it).

---

## 3. SINEHO USB-C Hub — 8-in-1 Multiport

**Link:** <https://www.amazon.it/dp/B0DN21FMH6>

Aluminium 8-in-1 USB-C adapter that adds the ports the Arduino Uno Q lacks.
Plug-and-play, bus-powered, portable.

| Spec | Value |
|---|---|
| HDMI | 4K @ 30 Hz |
| USB-C | 1× PD passthrough (100 W) + 1× data |
| USB-A | 1× USB 3.0 (5 Gbps) + 1× USB 2.0 |
| Network | Gigabit Ethernet (100 Mbps) |
| Card readers | SD + TF |

**Role in Serena:** wired Ethernet + extra USB ports for the board.

**Price:** **€19.99** (incl. IVA, Amazon.it).

---

## 4. Aione 100W 6-Port GaN Charger

**Link:** <https://www.amazon.it/Caricatore-Multiplo-Cellulare-Alimentatore-Caricabatterie/dp/B0DHZLQ6PK>

GaN charging station with six ports (3× USB-C + 3× USB-A) and 100 W total
output. PD + QC 3.0, GaN smart-chip protection (short-circuit, over-voltage,
overheating, over-current). Includes a 1.5 m extension cable.

| Spec | Value |
|---|---|
| USB-C | 3× (one up to 65 W) |
| USB-A | 3× (up to 20 W) |
| Total power | 100 W |
| Tech | GaN, PD, QC 3.0 |

**Role in Serena:** single-outlet power for the board and all peripherals.

**Price:** **€20.99** (incl. IVA, Amazon.it).

---

## Summary

| # | Component | Price (incl. VAT) |
|---|---|---|
| 1 | reSpeaker XVF3800 4-Mic Array | €57.73 * |
| 2 | Yealink SP92 Speakerphone | €69.99 |
| 3 | SINEHO USB-C Hub 8-in-1 | €19.99 |
| 4 | Aione 100W 6-Port Charger | €20.99 |
| | **Total** | **€168.70** |

\* USD price converted to EUR and Italian IVA (22%) applied — see Notes.

---

## Notes

- **Amazon.it prices** include Italian VAT (22%) by default.
- **Seeed price** is listed in USD on the Seeed Studio shop. The `seeed.cc`
  product page linked above is the product hub and is quote-based ("Request
  Quote"), so it shows no public price; the figure used here is the public shop
  price for the same product (reSpeaker XVF3800 4-Mic Array, SKU `100070894`).
  The board is configurable (with/without the optional XIAO ESP32S3 module,
  linear/circular layout) — **$51.43** is the default circular configuration;
  the base board without the XIAO module is a few dollars cheaper. Conversion
  used: **1 USD ≈ €0.92** (Jun 2026), plus 22% IVA, giving
  **$51.43 → €47.32 → €57.73**.
- Prices and availability were verified on 2026-06-23 and may differ at purchase
  time.
