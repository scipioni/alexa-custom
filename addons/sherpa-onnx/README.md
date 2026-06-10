# Cross-Compiling Accelerated sherpa-onnx for the Arduino UNO Q

**Date:** June 2026
**Host:** Arch Linux, x86-64
**Target:** Arduino UNO Q (Linux subsystem)
**Goal:** NEON-accelerated sherpa-onnx with Python bindings and an Italian 8-bit quantized ASR model

## 1. Target Platform

The Arduino UNO Q is a dual-brain board. Its Linux side — the relevant side for this project — is driven by a Qualcomm Dragonwing QRB2210 SoC with four 64-bit ARM Cortex-A53 cores (up to 2.0 GHz), an Adreno GPU, and 2 GB of RAM (a 4 GB variant exists), running a Debian-based Linux distribution. The companion STM32U585 microcontroller runs Zephyr/Arduino sketches and plays no role in speech recognition; it communicates with the Linux side through the Arduino Bridge.

From a compilation standpoint this makes the target a standard `aarch64-linux-gnu` Debian system. The Cortex-A53 implements the ARMv8.0-A baseline: NEON/ASIMD is always available, but the dot-product (`dotprod`) and half-precision (`fp16`) extensions introduced in later ARMv8 revisions are not. Tuning flags therefore target `-mcpu=cortex-a53` and nothing newer.

## 2. What "Accelerated" Means Here

On this hardware, practical acceleration means CPU inference through onnxruntime's NEON-optimized kernels, compiled with `-O3 -mcpu=cortex-a53 -ftree-vectorize`. Int8 quantization compounds this: the quantized GEMM paths in onnxruntime are substantially faster than fp32 on the A53 and roughly halve memory traffic, which matters on a 2 GB board.

The Adreno GPU and the Hexagon DSP are not reachable from a stock onnxruntime build on Linux. Exploiting them would require Qualcomm's QNN execution provider and AI SDK, a separate runtime path with its own model format; the sherpa-onnx project publishes dedicated QNN model builds for that route. It was deliberately left out of scope as a poor effort-to-benefit trade-off for a first deployment, but it remains the upgrade path if CPU inference proves too slow.

## 3. Build Strategy

The build is split into two stages because the two deliverables have different constraints.

### 3.1 Stage 1 — C++ binaries and libraries (true cross-compile)

The command-line tools (`sherpa-onnx-offline` and friends) and the static C API libraries are built with Arch's `aarch64-linux-gnu-gcc` cross toolchain through a custom CMake toolchain file. sherpa-onnx's build system automatically fetches a prebuilt aarch64 onnxruntime when cross-compiling, so no sysroot beyond Arch's `aarch64-linux-gnu-glibc` package is needed. Python, tests, websocket, JNI, and PortAudio support are disabled to keep the build lean; the C API stays enabled in case the project later wants to bypass Python for latency-critical paths. The result is packaged as `sherpa-onnx-aarch64-cli.tar.gz` and can be smoke-tested on the host with `qemu-aarch64-static` before ever touching the board.

### 3.2 Stage 2 — Python wheel (emulated native build)

A Python extension module must link against the exact Python interpreter and ABI present on the target. A bare cross toolchain on Arch has no access to the board's Debian Python headers and libraries, so the wheel is instead built inside an arm64 Debian container (`debian:trixie`, matched to the board's release) executed through QEMU user-mode emulation registered via binfmt. This is the standard manylinux-style approach: the build runs entirely on the x86-64 host, uses the same Cortex-A53 optimization flags (injected through `SHERPA_ONNX_CMAKE_ARGS`), and emits a wheel that installs directly on the board with pip.

The emulated build is slow — thirty to ninety minutes depending on the host — but it avoids the realistic risk of an out-of-memory failure when compiling onnxruntime-linked code natively on the board's 2 GB of RAM, and it keeps the board's eMMC free of build toolchains.

One configuration point must be verified before this stage: the Debian codename and Python version on the board (`cat /etc/os-release`, `python3 --version`). The container image must match, otherwise the wheel will target the wrong CPython ABI.

## 4. Italian Model Selection

The requirement was an Italian model quantized to 8 bits. Two candidates from the official sherpa-onnx model releases fit, with the choice driven by the board's RAM.

The default is **Whisper base (int8)**. It is multilingual with solid Italian coverage, ships int8-quantized encoder and decoder ONNX files in the official tarball, and its memory footprint fits comfortably on the 2 GB board. Italian is forced at runtime with `language="it"` rather than relying on auto-detection, which both removes a failure mode and skips the detection pass. The fp32 files are deleted after extraction to save eMMC space. If latency matters more than accuracy, Whisper tiny (int8) is a drop-in substitute with the same file layout.

The alternative, gated behind `MODEL_CHOICE=parakeet`, is **NeMo parakeet-tdt-0.6b-v3 (int8)**, which covers 25 European languages including Italian with markedly better accuracy. At 0.6 billion parameters it is only sensible on the 4 GB UNO Q variant.

Whisper is a non-streaming (offline) model: it transcribes complete utterances rather than producing words as they are spoken. For microphone-driven use this pairs naturally with the Silero VAD model that sherpa-onnx supports, segmenting speech before transcription.

## 5. Deliverables and Deployment

The build script (`build-sherpa-onnx-unoq.sh`) exposes subcommands for each stage — `deps`, `cli`, `wheel`, `model`, `all` — plus a `deploy` command that copies the wheel, the CLI bundle, and the model directory to the board over SSH, installs the wheel with pip (`--break-system-packages`, required on Debian's externally-managed Python), and verifies the import. A minimal usage example (`transcribe_it.py`) loads the int8 Whisper model with `num_threads=4` to saturate all four A53 cores and transcribes a 16 kHz mono WAV file in Italian.

### 5.1 Build sequence (host)

Stage 1 (CLI/libs) is a fast true cross-compile. Stages 2 and 3 can run in any order after that. Docker must be running for stage 2.

```bash
sudo systemctl start docker

bash build-sherpa-onnx-unoq.sh cli    # ~5–15 min; produces out/sherpa-onnx-aarch64-cli.tar.gz
bash build-sherpa-onnx-unoq.sh wheel  # ~30–90 min (QEMU); produces out/wheels/sherpa_onnx-*.whl
bash build-sherpa-onnx-unoq.sh model  # downloads out/models/sherpa-onnx-whisper-base/
```

### 5.2 Deploy to the board

```bash
bash build-sherpa-onnx-unoq.sh deploy user@uno-q.local
```

This scps the wheel to `/tmp/`, rsync-s `out/models/` to `~/models/`, installs the wheel with pip, and prints the installed path as a smoke-test.

### 5.3 On-board setup

Unpack the CLI tools once after deploy:

```bash
cd ~ && tar xzf /tmp/sherpa-onnx-aarch64-cli.tar.gz
export PATH=$HOME/install/bin:$PATH   # add to ~/.bashrc to persist
```

Verify the Python extension:

```bash
python3 -c "import sherpa_onnx; print(sherpa_onnx.__version__)"
```

### 5.4 Running offline ASR on the board

The whisper-base int8 tarball ships an encoder, decoder, and token file. Pass a 16 kHz mono WAV and force Italian to skip the language-detection pass:

```bash
sherpa-onnx-offline \
  --whisper-encoder=~/models/sherpa-onnx-whisper-base/base-encoder.int8.onnx \
  --whisper-decoder=~/models/sherpa-onnx-whisper-base/base-decoder.int8.onnx \
  --whisper-language=it \
  --tokens=~/models/sherpa-onnx-whisper-base/base-tokens.txt \
  your-audio.wav
```

For alexa-custom: set `stt.backend: sherpa_onnx` in `config.yaml` with the model paths pointing to `~/models/sherpa-onnx-whisper-base/`.

## 6. Limitations and Future Work

Performance expectations should stay modest: four Cortex-A53 cores place Whisper base int8 well above real-time factor 1 for batch transcription, but interactive latency will be noticeable for long utterances; tiny int8 or a VAD-segmented pipeline mitigates this. Accuracy on the 2 GB board is bounded by what Whisper base offers in Italian — upgrading to the 4 GB board unlocks the parakeet model. The QNN execution provider remains unexplored and is the main avenue for genuine hardware acceleration on this SoC. Finally, the wheel is tied to the board's Debian release; an OS upgrade on the UNO Q that changes the Python minor version requires rebuilding stage 2 with the matching container image.
