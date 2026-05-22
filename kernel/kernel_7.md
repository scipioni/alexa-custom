# Linux 7.0 for Arduino Q — Cross-Compilation & Bluetooth Audio Patch

Based on: https://rootcommit.com/2026/linux-7-0-arduino-q/

Target board: Arduino Imola / QRB2210 / QCM2290 (`uno-q`)
Goal: mainline Linux 7.0 with working full-duplex Bluetooth HFP audio (NewPie speakerphone)

---

## Problem: why Bluetooth mic is silent on the running 6.x kernel

The Qualcomm WCN399x Bluetooth chip routes received SCO audio (mic → host) via hardware
PCM pins through the LPASS (Low-Power Audio SubSystem) SoundWire controllers, not through
HCI. This means PipeWire only receives mic audio if LPASS initialises correctly.

LPASS fails to initialise because `clock-controller@a6a9000` (`qcom,sm6115-lpassaudiocc`)
is missing `#clock-cells = <1>` in the board DTS, so the LPI pinctrl driver cannot resolve
its required "audio" clock and defers indefinitely:

```
platform a7c0000.pinctrl: deferred probe pending:
  qcom-sm6115-lpass-lpi-pinctrl: Failed to get clk 'audio'
platform a610000.soundwire-controller: deferred probe pending: ...
platform a740000.soundwire-controller: deferred probe pending: ...
```

Without the SoundWire controllers, the LPASS audio subsystem never comes up and the
Bluetooth mic RX path (`hciconfig hci0` shows `sco:0` RX forever).

---

## Patch

Apply this to the kernel source before building. It targets
`arch/arm64/boot/dts/qcom/qcm2290.dtsi` (which `qrb2210-rb1.dts` includes).

```diff
diff --git a/arch/arm64/boot/dts/qcom/qcm2290.dtsi b/arch/arm64/boot/dts/qcom/qcm2290.dtsi
index XXXXXXX..YYYYYYY 100644
--- a/arch/arm64/boot/dts/qcom/qcm2290.dtsi
+++ b/arch/arm64/boot/dts/qcom/qcm2290.dtsi
@@ -... @@ (lpassaudiocc node)
 		lpassaudiocc: clock-controller@a6a9000 {
 			compatible = "qcom,sm6115-lpassaudiocc";
 			reg = <0 0xa6a9000 0 0x30000>;
+			#clock-cells = <1>;
 			#reset-cells = <1>;
 		};
 
@@ -... @@ (lpass_lpi_pinctrl node)
 		lpass_lpi_pinctrl: pinctrl@a7c0000 {
 			compatible = "qcom,qcm2290-lpass-lpi-pinctrl",
 				     "qcom,sm6115-lpass-lpi-pinctrl";
 			reg = <0 0xa7c0000 0 0x20000>,
 			      <0 0xa950000 0 0x10000>;
+			clocks = <&lpassaudiocc LPASS_AUDIO_HW_VOTE>;
+			clock-names = "audio";
 			gpio-controller;
 			#gpio-cells = <2>;
 			gpio-ranges = <&lpass_lpi_pinctrl 0 0 19>;
```

If the file is `sm6115.dtsi` (upstream may rename it), apply the same two hunks there.

`LPASS_AUDIO_HW_VOTE` is defined in
`include/dt-bindings/clock/qcom,sm6115-lpassaudiocc.h` — use the numeric constant
from that header if the symbol is not yet available at the DTS include stage.

---

## Cross-Compilation on Arch Linux

### 1. Install dependencies

```bash
sudo pacman -S git base-devel clang llvm lld openssl ncurses bc dtc python
```

The `clang` package on Arch includes `clang`, `llvm`, and `lld` — no separate packages
needed. `dtc` is the Device Tree Compiler (package `dtc`).

### 2. Clone Linux 7.0

```bash
git clone --depth=1 --branch v7.0 \
  https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git
cd linux
```

### 3. Apply the LPASS patch

Save the diff above as `lpass-audiocc-clock-cells.patch` then:

```bash
git apply lpass-audiocc-clock-cells.patch
```

Or edit the DTS file directly:

```bash
# add #clock-cells to lpassaudiocc
sed -i '/compatible = "qcom,sm6115-lpassaudiocc"/,/};/{
  /reg = /a\\t\t\t#clock-cells = <1>;
}' arch/arm64/boot/dts/qcom/qcm2290.dtsi

# verify
grep -A6 "lpassaudiocc:" arch/arm64/boot/dts/qcom/qcm2290.dtsi
```

Then add the `clocks`/`clock-names` lines to the `lpass_lpi_pinctrl` node manually in
`arch/arm64/boot/dts/qcom/qcm2290.dtsi` (or `sm6115.dtsi` — check which file defines the
`pinctrl@a7c0000` node in the 7.0 source tree).

### 4. Set build environment

```bash
export ARCH=arm64
export LLVM=1          # use clang/lld instead of gcc
export CROSS_COMPILE=  # not needed when LLVM=1; clang is natively cross-capable
```

### 5. Generate config

```bash
make defconfig
make nconfig
```

Inside `nconfig`, make the following selections:

| Setting | Action | Reason |
|---------|--------|--------|
| Platform selection → keep only **Qualcomm Platforms** | disable others | reduces build time |
| `CONFIG_DRM` (Device Drivers → Graphics) | **disable** | no display needed |
| `CONFIG_BT` (Networking → Bluetooth) | **keep ENABLED** | required — article says to disable, but we need HFP audio |
| `CONFIG_BT_HCIUART` | **enable** | WCN399x is a UART BT device |
| `CONFIG_BT_HCIUART_QCA` | **enable** | Qualcomm WCN399x UART protocol |
| `CONFIG_BT_MSFTEXT` | enable | mSBC codec for HFP wideband audio |
| `CONFIG_SND_SOC_SM8250` | **enable** (M) | Qualcomm LPASS audio machine driver |
| `CONFIG_SND_SOC_LPASS_RX_MACRO` | **enable** (M) | LPASS RX path |
| `CONFIG_SND_SOC_LPASS_TX_MACRO` | **enable** (M) | LPASS TX path |
| `CONFIG_SND_SOC_LPASS_VA_MACRO` | **enable** (M) | LPASS VA (voice activity) |
| `CONFIG_PINCTRL_SM6115_LPASS_LPI` | **enable** (M) | LPASS LPI pinctrl — must load for BT audio |
| `CONFIG_LPASS_CLK_SM6115` | **enable** (M) | LPASS clock driver |

Quick shell method to set values without nconfig:

```bash
scripts/config --enable CONFIG_BT
scripts/config --enable CONFIG_BT_HCIUART
scripts/config --enable CONFIG_BT_HCIUART_QCA
scripts/config --module CONFIG_SND_SOC_SM8250
scripts/config --module CONFIG_SND_SOC_LPASS_RX_MACRO
scripts/config --module CONFIG_SND_SOC_LPASS_TX_MACRO
scripts/config --module CONFIG_SND_SOC_LPASS_VA_MACRO
scripts/config --module CONFIG_PINCTRL_SM6115_LPASS_LPI
scripts/config --disable CONFIG_DRM
make olddefconfig    # resolve any new dependencies
```

### 6. Build

```bash
make -j$(nproc) Image dtbs modules
make modules_install INSTALL_MOD_PATH=/tmp/modules-out
```

Build artefacts:

| File | Path |
|------|------|
| Kernel image | `arch/arm64/boot/Image` |
| Device tree | `arch/arm64/boot/dts/qcom/qrb2210-rb1.dtb` |
| Modules | `/tmp/modules-out/lib/modules/7.0.0/` |

### 7. Package modules (optional)

```bash
make modules-cpio-pkg   # produces modules-7.0.0-arm64.cpio
```

---

## Deploying to the Board

Copy the three artefacts to the board's boot partition (partition 44 per the article):

```bash
scp arch/arm64/boot/Image arduino@uno-q:~/boot/
scp arch/arm64/boot/dts/qcom/qrb2210-rb1.dtb arduino@uno-q:~/boot/
# for modules — extract cpio or rsync the modules-out tree
```

Boot from U-Boot:

```
setenv bootargs root=/dev/mmcblk0p68 rootwait
load mmc 0:44 0x11ac00000 boot/Image
load mmc 0:44 0x10a200000 boot/qrb2210-rb1.dtb
booti 0x11ac00000 - 0x10a200000
```

---

## Verifying the Fix

After booting the patched kernel:

```bash
# LPASS pinctrl must be bound (no longer in deferred probe)
ls /sys/bus/platform/devices/a7c0000.pinctrl/driver

# SoundWire controllers must be up
ls /sys/bus/platform/devices/a610000.soundwire-controller/driver
ls /sys/bus/platform/devices/a740000.soundwire-controller/driver

# ALSA sound card must appear
cat /proc/asound/cards

# Bluetooth mic RX packets must increase while speaking into NewPie
hciconfig hci0   # watch sco:N in RX line — N must grow
```

Once LPASS is working, the full BT conference audio pipeline is:

```
NewPie mic → BT SCO RX → WCN399x → LPASS SoundWire → PipeWire capture → LiveKit TX
LiveKit RX → PipeWire playback → WCN399x SCO TX → BT → NewPie speaker
```

---

## Summary of Changes from the Article

| Article (Debian) | This document (Arch) |
|---|---|
| `apt-get install git build-essential llvm clang lld libssl-dev libncurses-dev` | `pacman -S git base-devel clang llvm lld openssl ncurses bc dtc python` |
| Disable `CONFIG_BT` | **Keep `CONFIG_BT` enabled** — required for HFP |
| No DTS patch | Apply LPASS audiocc `#clock-cells` patch |
| `CROSS_COMPILE=aarch64-linux-gnu-` | Not needed: `LLVM=1` makes clang self-sufficient for arm64 |
