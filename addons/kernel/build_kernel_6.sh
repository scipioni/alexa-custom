#!/usr/bin/env bash
# build_kernel_6.sh — patch, configure and build linux-qcom for Arduino UNO Q
#
# Usage:
#   cd /path/to/linux-qcom   (already cloned)
#   bash /home/arduino/livekit-client/build_kernel_6.sh
#
# Or pass the source directory explicitly:
#   bash /home/arduino/livekit-client/build_kernel_6.sh /path/to/linux-qcom

set -euo pipefail

# ── helpers ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
die()   { echo -e "${RED}[✗]${NC} $*" >&2; exit 1; }

# ── locate source tree ────────────────────────────────────────────────────────
SRC="${1:-$PWD}"
[[ -f "$SRC/Makefile" && -f "$SRC/Kbuild" ]] \
  || die "Not a kernel source tree: $SRC\nUsage: $0 [/path/to/linux-qcom]"
cd "$SRC"
info "Kernel source: $SRC"

# ── check tool prerequisites ──────────────────────────────────────────────────
for tool in clang llvm-ar llvm-nm llvm-objcopy llvm-strip ld.lld bc dtc; do
  command -v "$tool" &>/dev/null || die "Missing tool: $tool  (pacman -S clang llvm lld dtc bc)"
done

# ── 1. copy running kernel config ─────────────────────────────────────────────
LOCAL_CONFIG="/boot/config-6.16.7-g0dd6551ae96b"
[[ -f "$LOCAL_CONFIG" ]] || die "Local config not found: $LOCAL_CONFIG"
info "Copying $LOCAL_CONFIG → .config"
cp "$LOCAL_CONFIG" .config

# Strip the CC_VERSION_TEXT line — it encodes the original GCC version and causes
# a false "configuration changed" warning when building with clang.
sed -i '/^CONFIG_CC_VERSION_TEXT=/d' .config

# ── 2. patch qcm2290.dtsi: remove protection-domain guard ────────────────────
DTS="arch/arm64/boot/dts/qcom/qcm2290.dtsi"
[[ -f "$DTS" ]] || die "Expected DTS not found: $DTS"

if grep -q 'qcom,protection-domain.*msm/adsp/audio_pd' "$DTS"; then
  info "Patching $DTS: removing qcom,protection-domain from APR audio services"

  # Remove both lines of each protection-domain property inside the apr block.
  # The property spans exactly two source lines:
  #   qcom,protection-domain = "avs/audio",
  #                             "msm/adsp/audio_pd";
  perl -i -0pe \
    's/\t+qcom,protection-domain = "avs\/audio",\s*\n\s+"msm\/adsp\/audio_pd";\n//g' \
    "$DTS"

  # Verify all instances removed
  if grep -q 'msm/adsp/audio_pd' "$DTS"; then
    warn "Some protection-domain lines may remain — check $DTS manually"
  else
    info "All qcom,protection-domain guards removed from service@4/7/8"
  fi
else
  warn "protection-domain not found in $DTS — already patched or DTS differs"
fi

# ── 3. configure ──────────────────────────────────────────────────────────────
export ARCH=arm64
export LLVM=1

info "Running make olddefconfig (adapts config for clang + any new options)"
make olddefconfig

# Force a few settings that must differ from the running config:
#   • BT_MSFTEXT — enable mSBC wideband audio codec support
#   • DRM       — disable graphics (headless, saves ~8 min build time)
info "Applying targeted config overrides"
./scripts/config --enable  CONFIG_BT_MSFTEXT
./scripts/config --disable CONFIG_DRM
make olddefconfig   # re-resolve after manual changes

# ── 4. show final state of critical options ───────────────────────────────────
info "Critical config options:"
for opt in \
  CONFIG_BT CONFIG_BT_HCIUART CONFIG_BT_HCIUART_QCA CONFIG_BT_MSFTEXT \
  CONFIG_QCOM_APR \
  CONFIG_SND_SOC_QDSP6 CONFIG_SND_SOC_QDSP6_AFE_CLOCKS \
  CONFIG_SND_SOC_SM8250 CONFIG_SND_SOC_LPASS_RX_MACRO CONFIG_SND_SOC_LPASS_TX_MACRO \
  CONFIG_PINCTRL_SM6115_LPASS_LPI \
  CONFIG_DRM; do
  val=$(grep -m1 "^${opt}[=]" .config || grep -m1 "^# ${opt} " .config || echo "not set")
  printf "  %-45s %s\n" "$opt" "$val"
done

# ── 5. build ───────────────────────────────────────────────────────────────────
JOBS=$(nproc)
info "Building with $JOBS parallel jobs (Image + dtbs + modules)"
time make -j"$JOBS" Image dtbs modules

# ── 6. install modules to staging dir ────────────────────────────────────────
KVER=$(make -s kernelrelease)
STAGING="/tmp/kmodules-${KVER}"
rm -rf "$STAGING"
info "Installing modules to $STAGING"
make modules_install INSTALL_MOD_PATH="$STAGING"

# ── 7. print artefact locations and deploy commands ───────────────────────────
DTB="arch/arm64/boot/dts/qcom/qrb2210-arduino-imola.dtb"
IMAGE="arch/arm64/boot/Image"

echo
info "Build complete. Artefacts:"
printf "  Kernel image : %s\n"  "$SRC/$IMAGE"
printf "  Device tree  : %s\n"  "$SRC/$DTB"
printf "  Modules      : %s\n"  "$STAGING"
printf "  Kernel ver   : %s\n"  "$KVER"

echo
info "Deploy to board (replace uno-q with the board's hostname/IP):"
cat <<DEPLOY
  scp $SRC/$IMAGE       arduino@uno-q:~/boot/Image
  scp $SRC/$DTB         arduino@uno-q:~/boot/qrb2210-arduino-imola.dtb
  rsync -av $STAGING/   arduino@uno-q:/

  # On the board — copy modules-load config and reboot:
  ssh arduino@uno-q "sudo tee /etc/modules-load.d/qdsp6-audio.conf <<'EOF'
q6core
q6afe
q6afe-clocks
q6afe-dai
q6asm
q6asm-dai
q6adm
q6routing
EOF
"
DEPLOY

echo
info "U-Boot boot commands (adjust partition numbers if needed):"
cat <<'UBOOT'
  setenv bootargs root=/dev/mmcblk0p68 rootwait
  load mmc 0:44 0x11ac00000 boot/Image
  load mmc 0:44 0x10a200000 boot/qrb2210-arduino-imola.dtb
  booti 0x11ac00000 - 0x10a200000
UBOOT

echo
info "Post-boot verification commands (run on the board):"
cat <<'VERIFY'
  # APR audio services must be present
  ls /sys/bus/aprbus/devices/

  # LPASS LPI pinctrl must be bound
  ls /sys/bus/platform/devices/a7c0000.pinctrl/driver

  # ALSA sound card must appear
  cat /proc/asound/cards

  # BT SCO RX must increment while speaking into NewPie
  hciconfig hci0
VERIFY
