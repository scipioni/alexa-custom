# 🚀 Software Installation

## Prerequisites

- **Python**: 3.13+
- **Audio**: PipeWire 1.x + WirePlumber 0.5.x
- **Libraries**: PortAudio (`libportaudio2`)

---

## 0. Initial Setup & System Preparation

Configure network, SSH, and sudo permissions:

```bash
# Connect to WiFi
nmcli device wifi connect "Galileo Corporate" password galileowifi

# Configure sudoers
sudo su
visudo

# Enable and start SSH service
systemctl start ssh
systemctl enable ssh
```

---

## 1. System Dependencies

On Debian/Ubuntu/Armbian, install required packages, enable user lingering, and install Task:

```bash
# Install core dependencies
sudo apt-get install libportaudio2 portaudio19-dev python3-venv pulseaudio-utils alsa-utils

# Enable lingering for the arduino user
sudo loginctl enable-linger arduino

# Install Task runner
curl -1sLf 'https://dl.cloudsmith.io/public/task/task/setup.deb.sh' | sudo -E bash
sudo apt install task
```

---

## 2. Virtual Environment & Package

Clone the repository and set up the environment with `uv`:

```bash
# Clone the repository
git clone git@github.com:scipioni/serena.git
cd serena/

# Set up virtual environment and install package using uv
python3 -m venv .venv
source ~/serena/.venv/bin/activate
pip install uv
uv pip install -e .
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
