# 🚀 Software Installation

## Prerequisites

- **Python**: 3.13+
- **Audio**: PipeWire 1.x + WirePlumber 0.5.x
- **Libraries**: PortAudio (`libportaudio2`)
- **TTS**: Pico TTS (`libttspico-utils`)

---

## 1. System Dependencies

On Debian/Ubuntu/Armbian:
```bash
sudo apt-get install libportaudio2 portaudio19-dev python3-venv libttspico-utils
```

---

## 2. Virtual Environment & Package

Clone the repository and set up the environment:
```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

---

## 3. Vosk Speech Recognition Model

Download the required STT models (defaults to the small Italian model):
```bash
alexa-setup
```
- Use `--large` for the ~1.2 GB high-accuracy model.
- Use `--force` to overwrite an existing installation.

---

## 4. Verification

Run the loopback test to ensure your microphone and speakers are working correctly through the software stack:
```bash
alexa-audio
```
If you hear your own voice, the software is ready.
