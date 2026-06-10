#!/usr/bin/env bash
# =============================================================================
# build-sherpa-onnx-unoq.sh
#
# Cross-compile sherpa-onnx for the Arduino UNO Q (Linux side):
#   SoC      : Qualcomm Dragonwing QRB2210
#   CPU      : 4x ARM Cortex-A53 (aarch64), NEON/ASIMD
#   OS       : Debian (arm64)
#
# Host: Arch Linux amd64
#
# What it produces (in ./out/):
#   1. CLI binaries + C/C++ libs   (true cross-compile, aarch64 toolchain)
#   2. Python wheel for the board  (built in an arm64 Debian container
#                                   via QEMU binfmt — required because the
#                                   extension must link the board's Python)
#   3. Italian int8 ASR model      (Whisper base, multilingual int8)
#
# Usage:
#   ./build-sherpa-onnx-unoq.sh deps      # install host packages (sudo)
#   ./build-sherpa-onnx-unoq.sh cli       # stage 1: binaries/libs
#   ./build-sherpa-onnx-unoq.sh wheel     # stage 2: python wheel
#   ./build-sherpa-onnx-unoq.sh model     # stage 3: italian int8 model
#   ./build-sherpa-onnx-unoq.sh all       # everything
#   ./build-sherpa-onnx-unoq.sh deploy user@uno-q.local   # scp to board
# =============================================================================
set -euo pipefail

# ----------------------------- configuration --------------------------------
SHERPA_ONNX_VERSION="${SHERPA_ONNX_VERSION:-master}"   # or pin e.g. v1.12.x
WORK_DIR="${WORK_DIR:-$PWD/sherpa-onnx-unoq-build}"
OUT_DIR="${OUT_DIR:-$PWD/out}"

# Cortex-A53: armv8.0-a, NEON is baseline. No dotprod/fp16 extensions.
TARGET_CFLAGS="-O3 -mcpu=cortex-a53 -ftree-vectorize -funsafe-math-optimizations"

# IMPORTANT: match the board. SSH in and run:
#   cat /etc/os-release ; python3 --version
# UNO Q ships Debian 13 (trixie) at the time of writing. Adjust if needed.
DEBIAN_IMAGE="${DEBIAN_IMAGE:-debian:trixie}"

# Container runtime: docker or podman
CONTAINER="${CONTAINER:-docker}"

# Italian int8 model selection:
#   whisper-base : ~150 MB download, multilingual incl. Italian, int8 files
#                  included. Good fit for the 2 GB UNO Q. Non-streaming.
#   parakeet     : NeMo parakeet-tdt-0.6b-v3-int8, 25 EU languages incl.
#                  Italian, much better accuracy — only for the 4 GB board.
MODEL_CHOICE="${MODEL_CHOICE:-whisper-base}"

mkdir -p "$WORK_DIR" "$OUT_DIR"

# ----------------------------- stage 0: deps --------------------------------
install_deps() {
    echo ">>> Installing host dependencies (Arch Linux)"
    sudo pacman -S --needed --noconfirm \
        base-devel cmake git wget \
        aarch64-linux-gnu-gcc aarch64-linux-gnu-binutils \
        aarch64-linux-gnu-glibc aarch64-linux-gnu-linux-api-headers \
        qemu-user-static qemu-user-static-binfmt
    # docker/podman: install whichever you prefer if missing
    if ! command -v "$CONTAINER" &>/dev/null; then
        echo ">>> '$CONTAINER' not found, installing docker"
        sudo pacman -S --needed --noconfirm docker
        sudo systemctl enable --now docker
        echo ">>> You may need: sudo usermod -aG docker \$USER  (then re-login)"
    fi
    # Sanity check: binfmt registration for aarch64
    if [[ ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]]; then
        sudo systemctl restart systemd-binfmt
    fi
    echo ">>> Deps OK"
}

# ------------------------- fetch sherpa-onnx sources ------------------------
fetch_sources() {
    if [[ ! -d "$WORK_DIR/sherpa-onnx" ]]; then
        git clone https://github.com/k2-fsa/sherpa-onnx "$WORK_DIR/sherpa-onnx"
    fi
    cd "$WORK_DIR/sherpa-onnx"
    git fetch --all --tags
    git checkout "$SHERPA_ONNX_VERSION"
    cd - >/dev/null
}

# ---------------- stage 1: cross-compile CLI binaries + libs ----------------
build_cli() {
    fetch_sources
    echo ">>> Stage 1: cross-compiling C++ binaries/libs for aarch64 (Cortex-A53)"

    local TC_FILE="$WORK_DIR/aarch64-cortexa53.toolchain.cmake"
    cat > "$TC_FILE" <<EOF
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_C_COMPILER   aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
set(CMAKE_C_FLAGS_INIT   "${TARGET_CFLAGS}")
set(CMAKE_CXX_FLAGS_INIT "${TARGET_CFLAGS}")
set(CMAKE_FIND_ROOT_PATH /usr/aarch64-linux-gnu)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
EOF

    local BUILD="$WORK_DIR/build-cli"
    cmake -S "$WORK_DIR/sherpa-onnx" -B "$BUILD" \
        -DCMAKE_TOOLCHAIN_FILE="$TC_FILE" \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX="$BUILD/install" \
        -DBUILD_SHARED_LIBS=OFF \
        -DSHERPA_ONNX_ENABLE_PYTHON=OFF \
        -DSHERPA_ONNX_ENABLE_TESTS=OFF \
        -DSHERPA_ONNX_ENABLE_CHECK=OFF \
        -DSHERPA_ONNX_ENABLE_PORTAUDIO=OFF \
        -DSHERPA_ONNX_ENABLE_JNI=OFF \
        -DSHERPA_ONNX_ENABLE_C_API=ON \
        -DSHERPA_ONNX_ENABLE_WEBSOCKET=OFF \
        -DSHERPA_ONNX_ENABLE_GPU=OFF
    cmake --build "$BUILD" -j"$(nproc)" --target install

    tar -C "$BUILD" -czf "$OUT_DIR/sherpa-onnx-aarch64-cli.tar.gz" install
    echo ">>> CLI bundle: $OUT_DIR/sherpa-onnx-aarch64-cli.tar.gz"
    file "$BUILD/install/bin/sherpa-onnx-offline" || true
}

# ------------------ stage 2: python wheel (arm64 container) -----------------
build_wheel() {
    fetch_sources
    echo ">>> Stage 2: building Python wheel inside arm64 $DEBIAN_IMAGE (QEMU)"
    echo ">>> NOTE: emulation is slow — expect 30-90 min depending on host."

    "$CONTAINER" run --rm --platform linux/arm64 \
        -v "$WORK_DIR/sherpa-onnx:/src" \
        -v "$OUT_DIR:/out" \
        -e SHERPA_ONNX_CMAKE_ARGS="-DCMAKE_BUILD_TYPE=Release -DSHERPA_ONNX_ENABLE_GPU=OFF -DCMAKE_C_FLAGS='${TARGET_CFLAGS}' -DCMAKE_CXX_FLAGS='${TARGET_CFLAGS}'" \
        "$DEBIAN_IMAGE" bash -c '
            set -e
            apt-get update
            apt-get install -y --no-install-recommends \
                build-essential cmake git ca-certificates \
                python3-dev python3-pip python3-venv python3-build
            cd /src
            git config --global --add safe.directory /src
            python3 -m build --wheel --no-isolation -o /out/wheels || \
            python3 -m pip wheel . --no-deps -w /out/wheels
            chmod -R a+rw /out/wheels
        '
    echo ">>> Wheel(s) in $OUT_DIR/wheels/:"
    ls -lh "$OUT_DIR/wheels/"
}

# ---------------------- stage 3: italian int8 model -------------------------
download_model() {
    echo ">>> Stage 3: downloading Italian int8 model ($MODEL_CHOICE)"
    local MDIR="$OUT_DIR/models"
    mkdir -p "$MDIR"
    cd "$MDIR"

    case "$MODEL_CHOICE" in
      whisper-base)
        # Multilingual Whisper base; tarball includes int8 ONNX files.
        # Use language="it" at runtime. Fits the 2 GB UNO Q.
        local TARBALL="sherpa-onnx-whisper-base.tar.bz2"
        [[ -f "$TARBALL" ]] || wget -c \
          "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$TARBALL"
        tar xvf "$TARBALL"
        # Keep only the int8 files to save space on the board's eMMC
        rm -f sherpa-onnx-whisper-base/base-encoder.onnx \
              sherpa-onnx-whisper-base/base-decoder.onnx
        ;;
      parakeet)
        # NeMo parakeet-tdt-0.6b-v3 int8: 25 EU languages incl. Italian.
        # Only for the 4 GB UNO Q — too large for the 2 GB model.
        local TARBALL="sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"
        [[ -f "$TARBALL" ]] || wget -c \
          "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$TARBALL"
        tar xvf "$TARBALL"
        ;;
      *)
        echo "Unknown MODEL_CHOICE=$MODEL_CHOICE"; exit 1 ;;
    esac
    cd - >/dev/null
    echo ">>> Model ready under $MDIR"
}

# ------------------------------- deploy -------------------------------------
deploy() {
    local TARGET="${1:?usage: $0 deploy user@host}"
    echo ">>> Deploying to $TARGET"
    scp "$OUT_DIR"/wheels/sherpa_onnx-*.whl "$TARGET:/tmp/" || true
    scp "$OUT_DIR"/sherpa-onnx-aarch64-cli.tar.gz "$TARGET:/tmp/" || true
    rsync -avz "$OUT_DIR/models/" "$TARGET:~/models/"
    ssh "$TARGET" '
        python3 -m pip install --user --break-system-packages /tmp/sherpa_onnx-*.whl
        python3 -c "import sherpa_onnx; print(\"sherpa-onnx\", sherpa_onnx.__file__)"
    '
    echo ">>> Done. Test on the board with the usage snippet in the README."
}

# -------------------------------- main ---------------------------------------
case "${1:-all}" in
    deps)   install_deps ;;
    cli)    build_cli ;;
    wheel)  build_wheel ;;
    model)  download_model ;;
    all)    build_cli; build_wheel; download_model ;;
    deploy) shift; deploy "$@" ;;
    *) echo "usage: $0 {deps|cli|wheel|model|all|deploy user@host}"; exit 1 ;;
esac
