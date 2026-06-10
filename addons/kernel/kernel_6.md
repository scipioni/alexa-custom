# Linux 6.16.7 for Arduino UNO Q — Cross-Compilation & Bluetooth Audio Fix

Source: https://github.com/arduino/linux-qcom  
Branch: `qcom-v6.16.7-unoq`  
Top commit: `0dd6551` ("arm64: qrb2210: support Arduino UNO Q")  
Board DTS: `arch/arm64/boot/dts/qcom/qrb2210-arduino-imola.dts`

---

## Root Cause: Why Bluetooth Mic is Silent

The full causal chain, confirmed by live system inspection:

```
BT mic broken
└── LPASS SoundWire controllers stuck in deferred probe
    └── LPASS LPI pinctrl (a7c0000.pinctrl) can't get clk "audio"
        └── clock comes from q6afecc inside APR service@4
            └── APR service@4 gated by qcom,protection-domain
                = "avs/audio", "msm/adsp/audio_pd"
                └── ADSP audio protection domain never reported available
                    via QMI to qcom_pd_mapper
                    → APR bus has zero devices
                    → q6afecc never probes
```

Every LPASS clock used by rxmacro, txmacro, and lpass_tlmm comes from `q6afecc`
(phandle `<0x1c>` in the compiled DTB, `qcom,q6afe-clocks` inside `service@4`).
Unlike kernel_7.md's approach (which uses the hardware `lpassaudiocc`), the Arduino
fork wires everything through the ADSP's Q6 AFE clock service. If that service doesn't
start, the entire LPASS audio subsystem — including the Bluetooth SCO receive path —
never initialises.

The ADSP boots successfully and the APR GLINK channel is established
(`ab00000.remoteproc:glink-edge.apr_audio_svc` rpmsg device is present, APR rpmsg
driver is bound). But the `qcom,protection-domain` property on `service@4` requires
`msm/adsp/audio_pd` to be registered with the PDR mapper before the APR audio services
start. The firmware at `qcom/qcm2290/adsp.mbn` does not expose this QMI service, so
the APR bus stays empty, q6afecc never exists, and `devm_clk_get(dev, "audio")` fails
forever.

---

## Patch

One surgical change to `arch/arm64/boot/dts/qcom/qcm2290.dtsi`: remove the protection
domain guard from `service@4`. The APR audio services then start as soon as the ADSP
GLINK channel is up, without waiting for a QMI PD registration that never arrives.

```diff
diff --git a/arch/arm64/boot/dts/qcom/qcm2290.dtsi b/arch/arm64/boot/dts/qcom/qcm2290.dtsi
--- a/arch/arm64/boot/dts/qcom/qcm2290.dtsi
+++ b/arch/arm64/boot/dts/qcom/qcm2290.dtsi
@@ -... @@ (inside remoteproc@ab00000 / glink-edge / apr)
 			service@4 {
 				compatible = "qcom,q6afe";
 				reg = <0x4>;
-				qcom,protection-domain = "avs/audio",
-							 "msm/adsp/audio_pd";
 
 				dais {
 					#address-cells = <1>;
```

> **Why this is safe here:** the protection domain mechanism exists to restart audio
> services if the ADSP audio PD crashes. On this board the ADSP firmware does not
> implement PD restart for the audio domain at all, so removing the guard has no
> functional downside — the APR service was simply never starting without it.

### Also patch service@7 (q6asm) and service@8 (q6adm)

Apply the same removal to `service@7` and `service@8` if they also have
`qcom,protection-domain`; without q6asm and q6adm the ALSA sound card (q6routing,
q6asmdai) won't probe either.

```diff
@@ -... @@ service@7
 			service@7 {
 				compatible = "qcom,q6asm";
 				reg = <0x7>;
-				qcom,protection-domain = "avs/audio",
-							 "msm/adsp/audio_pd";
 
@@ -... @@ service@8
 			service@8 {
 				compatible = "qcom,q6adm";
 				reg = <0x8>;
-				qcom,protection-domain = "avs/audio",
-							 "msm/adsp/audio_pd";
```

---

## Module Loading Fix

The QDSP6 audio modules are built as `=m` but are **not loaded at boot**. Without them,
even after the DTS patch the APR service devices have no matching driver. Add a
modules-load fragment so they are inserted before the APR rpmsg driver binds to
`apr_audio_svc`:

```bash
sudo tee /etc/modules-load.d/qdsp6-audio.conf << 'EOF'
q6core
q6afe
q6afe-clocks
q6afe-dai
q6asm
q6asm-dai
q6adm
q6routing
EOF
```

After adding this file, regenerate the initramfs if you use one:

```bash
sudo mkinitcpio -P    # Arch Linux
```

---

## Cross-Compilation on Arch Linux

### 1. Install dependencies

```bash
sudo pacman -S git base-devel clang llvm lld openssl ncurses bc dtc python perl
```

### 2. Clone the Arduino fork

```bash
# Stable tag (matches the board's running kernel)
git clone --depth=1 --branch qcom-v6.16.7 \
  https://github.com/arduino/linux-qcom.git
cd linux-qcom
```

To build from the latest development branch instead:

```bash
git clone --depth=1 --branch qcom-v6.16.7-unoq \
  https://github.com/arduino/linux-qcom.git
cd linux-qcom
```

### 3. Run the build script

The build script `build_kernel_6.sh` automates all remaining steps: patching the DTS,
seeding the config from the running board's `/boot/config-6.16.7-g0dd6551ae96b`,
building, and printing the deploy commands.

```bash
bash ~/livekit-client/build_kernel_6.sh /path/to/linux-qcom
```

Or if you are already inside the cloned directory:

```bash
bash ~/livekit-client/build_kernel_6.sh
```

The script performs these steps in order (see the next section for the manual
equivalent):

1. Copies `/boot/config-6.16.7-g0dd6551ae96b` as `.config`
2. Strips the `CONFIG_CC_VERSION_TEXT` line (avoids false GCC↔clang mismatch warning)
3. Applies the `qcom,protection-domain` removal patch to `qcm2290.dtsi`
4. Runs `make olddefconfig` (`ARCH=arm64 LLVM=1`) to resolve any new/removed options
5. Enables `CONFIG_BT_MSFTEXT` (mSBC wideband) and disables `CONFIG_DRM` (headless)
6. Builds `Image`, `dtbs`, `modules`
7. Installs modules to `/tmp/kmodules-<version>/`
8. Prints `scp`/`rsync` deploy commands and U-Boot commands

---

### Manual steps (equivalent to the script)

#### a. Seed config from running board

```bash
cp /boot/config-6.16.7-g0dd6551ae96b .config
sed -i '/^CONFIG_CC_VERSION_TEXT=/d' .config
```

The running board's config already has all required audio and BT options enabled as
modules (`CONFIG_SND_SOC_QDSP6_AFE_CLOCKS=m`, `CONFIG_QCOM_APR=m`,
`CONFIG_PINCTRL_SM6115_LPASS_LPI=m`, etc.) — no further config surgery is needed
beyond the two lines below.

#### b. Apply targeted overrides

```bash
export ARCH=arm64
export LLVM=1
./scripts/config --enable  CONFIG_BT_MSFTEXT   # mSBC wideband codec
./scripts/config --disable CONFIG_DRM          # headless — saves ~8 min build time
make olddefconfig
```

#### c. Apply the DTS patch

```bash
perl -i -0pe \
  's/\t+qcom,protection-domain = "avs\/audio",\s*\n\s+"msm\/adsp\/audio_pd";\n//g' \
  arch/arm64/boot/dts/qcom/qcm2290.dtsi

# Verify
grep 'msm/adsp/audio_pd' arch/arm64/boot/dts/qcom/qcm2290.dtsi
# Expected: no output
```

#### d. Build

```bash
make -j$(nproc) Image dtbs modules
make modules_install INSTALL_MOD_PATH=/tmp/kmodules-$(make -s kernelrelease)
```

Build artefacts:

| File | Path |
|------|------|
| Kernel image | `arch/arm64/boot/Image` |
| Device tree | `arch/arm64/boot/dts/qcom/qrb2210-arduino-imola.dtb` |
| Modules | `/tmp/kmodules-<version>/lib/modules/<version>/` |

> **Important:** use `qrb2210-arduino-imola.dtb`, not `qrb2210-rb1.dtb`. The rb1 DTS
> has no audio or QDSP6 nodes.

### Deploy

```bash
KVER=$(make -s kernelrelease)
scp arch/arm64/boot/Image                              arduino@uno-q:~/boot/
scp arch/arm64/boot/dts/qcom/qrb2210-arduino-imola.dtb arduino@uno-q:~/boot/
rsync -av /tmp/kmodules-${KVER}/                       arduino@uno-q:/
```

Boot from U-Boot:

```
setenv bootargs root=/dev/mmcblk0p68 rootwait
load mmc 0:44 0x11ac00000 boot/Image
load mmc 0:44 0x10a200000 boot/qrb2210-arduino-imola.dtb
booti 0x11ac00000 - 0x10a200000
```

---

## Verifying the Fix

After booting the patched kernel with the modules-load fragment in place:

```bash
# 1. APR bus must have devices
ls /sys/bus/aprbus/devices/
# Expected: service@3, service@4, service@7, service@8

# 2. q6afecc clock controller must appear
find /sys/bus/ -name "*q6afe-clock*" 2>/dev/null
# Expected: a driver entry

# 3. LPASS LPI pinctrl must be bound
ls /sys/bus/platform/devices/a7c0000.pinctrl/driver

# 4. SoundWire controllers must be bound
ls /sys/bus/platform/devices/a610000.soundwire-controller/driver
ls /sys/bus/platform/devices/a740000.soundwire-controller/driver

# 5. ALSA sound card must appear
cat /proc/asound/cards
# Expected: qrb2210-arduino or similar entry

# 6. BT mic RX packets must increase while speaking into NewPie
hciconfig hci0
# Watch: RX ... sco:N — N must increment while speaking
```

---

## Relationship to kernel_7.md

| Aspect | kernel_6 (this doc) | kernel_7 |
|--------|---------------------|----------|
| Source | `github.com/arduino/linux-qcom` | `git.kernel.org` mainline |
| Branch/tag | `qcom-v6.16.7-unoq` | `v7.0` |
| LPASS clock source | q6afecc (ADSP Q6 virtual clock) | lpassaudiocc (hardware clock) |
| Root cause | APR service@4 PD guard blocks q6afecc probe | lpassaudiocc missing `#clock-cells` |
| Patch target | `qcom,protection-domain` removal in `service@4/7/8` | `#clock-cells = <1>` on lpassaudiocc |
| Audio stack | Full Q6DSP/APM audio (ADSP-managed clocks) | LPASS hardware-only path |
| BT DTS | `qrb2210-arduino-imola.dts` (sound card included) | `qrb2210-rb1.dts` (no audio) |

The kernel_6 Arduino fork is the preferred base for production use because the full
Q6DSP audio stack (once working) gives better BT echo cancellation, noise suppression,
and audio mixing than the hardware-only LPASS path.
