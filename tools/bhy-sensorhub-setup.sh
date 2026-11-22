#!/bin/bash
# =============================================================================
#  bhy-sensorhub-setup.sh — 把 C7 的传感器中枢（Bosch BHI）装进 4.9 内核树
#
#  用法: bash tools/bhy-sensorhub-setup.sh [内核树路径]      # 默认 work/kernel-4.9
#
#  为什么必须搬：ROM 里注入的传感器 HAL 是**三星原厂**的
#  vendor/lib(64)/hw/sensors.msm8953.so，它说话的对象就是 BHI 内核驱动；
#  donor（小米 mido）的传感器栈走的是高通 SSC，两者不通用。没有 BHI 驱动，
#  传感器（加速度/陀螺/磁力/气压/霍尔…）一律不可用。
#
#  搬什么（取自 work/samsung-msm8953-3.18.tar.gz）：
#    drivers/misc/bhy/{bhy_core.c(212KB), bhy_i2c.c, bstclass.c, *.h, Kconfig, Makefile}
#    kernel/bhy-3.18-source/msm8953-c7ltechn-bhy.dtsi  →  内核树 DTS
#
#  接线（幂等）：
#    drivers/misc/Kconfig  += source "drivers/misc/bhy/Kconfig"
#    drivers/misc/Makefile += obj-$(CONFIG_SENSORS_BHI) += bhy/
#    c7ltechn_defconfig    += CONFIG_SENSORS_BHI=y
#    DTS：安装 bhy dtsi + 主 dts 加 include + pinctrl 补 i2c_5_active/i2c_5_sleep
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
K="${1:-$ROOT/work/kernel-4.9}"
TB="$ROOT/work/samsung-msm8953-3.18.tar.gz"
D=android_kernel_samsung_msm8953-lineage-16.0

[ -d "$K" ] || { echo "找不到内核树: $K"; exit 1; }

echo "[1/4] 从 3.18 包取 BHI 驱动"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
tar xzf "$TB" -C "$TMP" --wildcards "$D/drivers/misc/bhy/*" "$D/drivers/sensors/sensors_core.c" \
	"$D/include/linux/sensor/sensors_core.h" 2>/dev/null
mkdir -p "$K/drivers/misc/bhy" "$K/drivers/sensors" "$K/include/linux/sensor"
cp -f "$TMP/$D/drivers/misc/bhy/"* "$K/drivers/misc/bhy/"
# bhy_core.h 里 include <linux/sensor/sensors_core.h>，而它对应的实现是
# drivers/sensors/sensors_core.c（369 行，号称 "Sensors Class"，建 /sys/class/sensors）。
# 三星 HAL 就是读这个 class，所以这两样是 BHY 的必需依赖。
cp -f "$TMP/$D/drivers/sensors/sensors_core.c" "$K/drivers/sensors/"
cp -f "$TMP/$D/include/linux/sensor/sensors_core.h" "$K/include/linux/sensor/"
cat > "$K/drivers/sensors/Makefile" <<'MK'
# C7ROM: 只搬 BHY 需要的 sensors 核心（其余三星机型 sensor 驱动不搬）
obj-$(CONFIG_SENSORS_CORE)	+= sensors_core.o
MK
if ! grep -q "config SENSORS_CORE" "$K/drivers/sensors/Kconfig" 2>/dev/null; then
cat > "$K/drivers/sensors/Kconfig" <<'KF'
# C7ROM: BHI 传感器中枢依赖的 sensors class（/sys/class/sensors）
config SENSORS_CORE
	bool "Samsung sensors class support (/sys/class/sensors)"
	help
	  This option enables the sensor sysfs class in /sys/class/sensors.
	  The Samsung sensor HAL (vendor/lib(64)/hw/sensors.msm8953.so) reads
	  this class, and the Bosch BHI sensor hub driver needs it too.
	  Ported from the Samsung msm8953 3.18 tree by the C7ROM project.
KF
fi

echo "[2/4] 接线（Kconfig / Makefile / defconfig）"
add_line() { grep -qF "$2" "$1" || printf '%s\n' "$2" >> "$1"; }
if ! grep -q 'misc/bhy/Kconfig' "$K/drivers/misc/Kconfig"; then
  { echo ""; echo "# C7ROM: Bosch BHI 传感器中枢（C7 原厂传感器 HAL 的内核侧）";
    echo 'source "drivers/misc/bhy/Kconfig"'; } >> "$K/drivers/misc/Kconfig"
fi
add_line "$K/drivers/misc/Makefile" 'obj-$(CONFIG_SENSORS_BHI)	+= bhy/'
if ! grep -q 'sensors/Kconfig' "$K/drivers/Kconfig"; then
  { echo ""; echo "# C7ROM: 三星 sensors class（BHI 依赖）"; echo 'source "drivers/sensors/Kconfig"'; } >> "$K/drivers/Kconfig"
fi
add_line "$K/drivers/Makefile" 'obj-$(CONFIG_SENSORS_CORE)	+= sensors/'
add_line "$K/arch/arm64/configs/c7ltechn_defconfig" 'CONFIG_SENSORS_CORE=y'
add_line "$K/arch/arm64/configs/c7ltechn_defconfig" 'CONFIG_SENSORS_BHI=y'
# BHY 走 IIO 的 triggered buffer（4.9 的 iio_triggered_buffer_setup 实现放在这里）
add_line "$K/arch/arm64/configs/c7ltechn_defconfig" 'CONFIG_IIO=y'
add_line "$K/arch/arm64/configs/c7ltechn_defconfig" 'CONFIG_IIO_BUFFER=y'
add_line "$K/arch/arm64/configs/c7ltechn_defconfig" 'CONFIG_IIO_TRIGGERED_BUFFER=y'

echo "[3/4] DTS：安装 bhy dtsi + 主 dts include + i2c_5 pinctrl"
cp -f "$ROOT/kernel/bhy-3.18-source/msm8953-c7ltechn-bhy.dtsi" "$K/arch/arm64/boot/dts/qcom/"
python3 - "$K" <<'PY'
import sys, os
K = sys.argv[1]
dts = os.path.join(K, "arch/arm64/boot/dts/qcom/msm8953-c7ltechn.dts")
pinctrl = os.path.join(K, "arch/arm64/boot/dts/qcom/msm8953-c7ltechn-pinctrl.dtsi")

# 3a. 主 dts 里的 include（排在 nfc 之后）
s = open(dts).read()
line = '#include "msm8953-c7ltechn-bhy.dtsi"'
if line not in s:
    anchor = '#include "msm8953-c7ltechn-nfc.dtsi"'
    if anchor not in s:
        raise SystemExit("主 dts 里找不到 nfc include 锚点")
    s = s.replace(anchor, anchor + "\n" + line, 1)
    open(dts, "w").write(s)
    print("    主 dts 已加 include")

# 3b. pinctrl：i2c_5 的 active/sleep。
# ★ 4.9 基线 msm8953-pinctrl.dtsi 里**本来就有** i2c_5_active/i2c_5_sleep
#   （gpio18/19 + blsp_i2c5，与三星一致），所以正常什么都不用加；
#   必须先查基线，否则重复定义 label 会让 dtc 报 "Input tree has errors"。
base = os.path.join(K, "arch/arm64/boot/dts/qcom/msm8953-pinctrl.dtsi")
base_has = os.path.isfile(base) and "i2c_5_active:" in open(base).read()
p = open(pinctrl).read()
if base_has:
    print("    基线 dtsi 已有 i2c_5_active/i2c_5_sleep，跳过")
elif "i2c_5_active:" not in p:
    block = """	i2c_5_active: i2c_5_active {
		mux {
			pins = "gpio18", "gpio19";
			function = "blsp_i2c5";
		};
		config {
			pins = "gpio18", "gpio19";
			drive-strength = <2>;
			bias-disable;
		};
	};
	i2c_5_sleep: i2c_5_sleep {
		mux {
			pins = "gpio18", "gpio19";
			function = "blsp_i2c5";
		};
		config {
			pins = "gpio18", "gpio19";
			drive-strength = <2>;
			bias-disable;
		};
	};
"""
    anchor = "	i2c_6_sleep: i2c_6_sleep {"
    i = p.find(anchor)
    if i < 0:
        raise SystemExit("pinctrl 里找不到 i2c_6_sleep 锚点")
    # 插到 i2c_6_sleep 这个 state 结束之后
    j = p.find("\n\t};\n", p.find("};", p.find("config {", i))) + len("\n\t};\n")
    p = p[:j] + block + p[j:]
    open(pinctrl, "w").write(p)
    print("    pinctrl 已补 i2c_5_active / i2c_5_sleep")
PY

echo "[4/4] 结构修补（3.18 → 4.9 的 IIO API）"
python3 "$ROOT/tools/bhy-fixes.py" "$K"

cat <<EOF

完成。编译验证：
cat <<EOF
  cd $K && ./scripts/config --file out/.config --enable SENSORS_BHI
  make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \\
       CROSS_COMPILE_ARM32=arm-linux-gnueabi- olddefconfig
  make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \\
       CROSS_COMPILE_ARM32=arm-linux-gnueabi- -j1 drivers/misc/bhy/
EOF
