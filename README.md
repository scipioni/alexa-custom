<p align="center">
  <span style="font-size: 3.5em; font-weight: 900; letter-spacing: -2px; vertical-align: middle; background: linear-gradient(135deg, #4ade80, #60a5fa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">Serena</span>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="docs/logo_serena.png" alt="Serena" height="120" align="middle">
</p>

<p align="center">
  <em>The voice assistant that answers to you — not to a data center.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python_3.13-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.13">
  <img src="https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black" alt="Linux">
  <img src="https://img.shields.io/badge/sherpa--onnx-blueviolet?style=for-the-badge" alt="sherpa-onnx">
  <img src="https://img.shields.io/badge/Piper--TTS-success?style=for-the-badge" alt="Piper TTS">
  <img src="https://img.shields.io/badge/Home_Assistant-41BDF5?style=for-the-badge&logo=homeassistant&logoColor=white" alt="Home Assistant">
  <img src="https://img.shields.io/badge/Apache_2.0-D22128?style=for-the-badge&logo=apache&logoColor=white" alt="Apache 2.0">
</p>

---

## 🔕 Ale*a, you're fired

You know the drill: you buy a smart speaker, and in return it ships every word spoken in your living room to someone else's cloud, stops working when your internet hiccups, and one day the vendor decides which features you're allowed to keep.

**Serena flips that deal.** Take a cheap Linux board (an Arduino Uno Q), plug in any USB speakerphone, and you get an Italian-speaking voice assistant where everything that matters happens **on the device**:

- 👂 **Listening** — sherpa-onnx speech-to-text runs locally, always on, no audio ever leaves the room
- 🗣️ **Speaking** — Piper neural TTS synthesizes natural Italian voices offline
- 🧠 **Understanding** — wake words and commands are matched with Italian phonetic fuzzy matching, in plain YAML you control
- 🏠 **Acting** — lights, shutters, heating via MQTT and Home Assistant auto-discovery; shell commands; Telegram alerts; voice calls via LiveKit

No subscription. No account. No "sorry, something went wrong" from a server across the ocean. The cloud is strictly **opt-in** — connect an LLM for free-form chat or LiveKit for calls only if *you* want to.

---

## ✨ What it does

| | |
|---|---|
| 🧠 **Always-on local STT** | One free-vocabulary sherpa-onnx model transcribes continuously — wake word and command detection in a single pass, low latency. |
| ⚡ **One-breath commands** | *"Serena, accendi la luce"* — wake word and command in a single utterance, matched instantly. |
| 🗣️ **Neural Italian TTS** | Piper speaks with natural intonation, fully offline, zero API fees. |
| 🏠 **Home Assistant native** | Auto-registers via MQTT Discovery — point it at your broker and you're done. |
| 📞 **Voice calls** | Says the word and joins a LiveKit room — perfect for elderly-care check-ins and emergency calls. |
| 🤖 **Teach it by voice** | Say *"impara nuovo comando"* and define new triggers interactively — no YAML editing needed. |
| 🖥️ **Live web dashboard** | VU meters, STT status, streaming logs, and a full config editor at `http://<host>:8080`. |
| 🔄 **Hot-reload everything** | Edit wake words, triggers, or settings while it runs — changes apply in ~2 seconds. |

> **User:** *Galileo, che ore sono?*
> **Serena:** *Sono le 15 e 42.*

### Speech models

Serena ships pinned to Italian by default, but both the STT and TTS engines have ready-made models for English too:

| | STT — [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (Kroko Zipformer) | TTS — [Piper](https://github.com/rhasspy/piper) |
|---|---|---|
| 🇮🇹 Italian | [`it/kroko_64l`](https://huggingface.co/hudaiapa88/sherpa-stt-onnx/tree/main/it) | [`it_IT-paola-medium`](https://huggingface.co/rhasspy/piper-voices/tree/main/it/it_IT/paola/medium) |
| 🇬🇧 English | [`en/kroko_64l`](https://huggingface.co/hudaiapa88/sherpa-stt-onnx/tree/main/en) | [`en_US-amy-medium`](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium) |

`serena-setup` downloads the Italian pair automatically; point `stt.model_path` / `tts.voice` at the English models above to run Serena in English instead.

---

## 🚀 Quick Start

```bash
# 1. System dependencies (Debian 13)
sudo apt install -y python3-venv pipewire pulseaudio-utils alsa-utils libportaudio2 task mosquitto-clients
sudo apt install -y libgstreamer1.0-dev gstreamer1.0-plugins-bad gstreamer1.0-tools gstreamer1.0-pipewire python3-gst-1.0

# 2. Python environment + install
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[gstreamer]

# 3. Download speech models (sherpa-onnx, Piper)
serena-setup

# 4. Audio routing (run once)
task audio:setup
task setup:gstreamer

# 5. Configuration
cp -a conf.example conf

# 6. Run as a service...
task setup
sudo loginctl enable-linger $(whoami)
systemctl --user start serena

# ...or directly
serena-client
```

Open **http://localhost:8080** for the web dashboard.

> 💡 Full installation guide, audio troubleshooting, and configuration reference: [details.md](details.md)

---

## ⚙️ Configuration

Everything lives in `conf/` as plain YAML, hot-reloaded while the daemon runs:

```yaml
wake_words:
  - "ehi serena"

triggers:
  - commands: ["che ore sono"]
    actions:
      - type: shell
        command: date +%H:%M
  - commands: ["accendi la luce"]
    actions:
      - type: mqtt_publish
        topic: home/light/set
        payload: "ON"
```

17+ action types: shell, MQTT, Telegram, LiveKit calls, LLM chat, volume, weather, and more. See the [configuration reference](docs/configuration.md).

---

## 🔩 Requirements

| Hardware | Software |
|---|---|
| Linux board (aarch64, 2+ GB RAM) | Debian 13 (Trixie) or similar |
| USB speakerphone | PipeWire 1.4+ with PulseAudio compat |
| Optional: LED matrix / I2C OLED | Python 3.13+ |

Optimized for the **Arduino Uno Q**, but runs on any Linux system with PipeWire.

---

## 📚 Documentation

| Guide | What's inside |
|---|---|
| [→ Technical Reference](details.md) | Full architecture, config reference, CLI, audio pipeline, STT, actions |
| [→ Bill of Materials](docs/BOM.md) | Hardware add-ons with prices and links |
| [→ Hardware Setup](docs/setup_hardware.md) | PipeWire configuration, board-specific fixes |
| [→ Home Assistant](docs/homeassistant.md) | Mosquitto + HA Core setup, connecting Serena |
| [→ Troubleshooting](docs/troubleshooting.md) | Common issues: audio, connection, permissions |

---

## 🤝 Contributing

Contributions welcome! Open an issue first for significant changes.

```bash
task test          # run regression tests
task lint          # ruff check + format check
task fix           # auto-fix, format, and test
```

---

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/Apache_2.0-D22128?style=for-the-badge&logo=apache&logoColor=white" alt="Apache 2.0"></a>
</p>
<p align="center">
  Made by Galileo Team for privacy-first voice assistants
</p>
