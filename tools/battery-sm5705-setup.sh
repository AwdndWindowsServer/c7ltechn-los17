#!/bin/bash
# =============================================================================
#  battery-sm5705-setup.sh — 把 C7 的 SM5705 电池栈（Samsung 3.18）搬进 4.9 内核树
#
#  用法: bash tools/battery-sm5705-setup.sh [内核树路径]      # 默认 work/kernel-4.9
#
#  搬什么（都取自 work/samsung-msm8953-3.18.tar.gz，即公开的三星 msm8953 3.18 树）：
#    drivers/battery/{sec_battery.c, sec_step_charging.c,
#                      sm5705_charger.c, sm5705_charger_oper.c, sm5705_fuelgauge.c}
#        + 我们自己的最小 Makefile（三星原版会去编一堆别的机型的驱动）
#    include/linux/battery/**            电池栈头（22 个）
#    include/linux/mfd/sm5705/sm5705.h   MFD 寄存器头
#    include/linux/muic/**               MUIC 枚举/类型（电池代码无条件要用 ATTACHED_DEV_*）
#    include/linux/leds/**               闪光灯头（sm5705.h 会引）
#    include/linux/sec_{param,jack}.h, usb_notify.h, vbus_notifier.h
#    drivers/usb/notify/**                USB 通知层（充电器/线缆状态用）
#    + 7 个 4.9 树里没有、三星驱动要用的头（proportions.h 等，只补缺、不覆盖）
#
#  接线（幂等）：
#    drivers/Makefile += battery/        drivers/Kconfig += battery/Kconfig
#    drivers/usb/Makefile += notify/     drivers/usb/Kconfig += notify/Kconfig
#    c7ltechn_defconfig += BATTERY_SAMSUNG / CHARGER_SM5705 / FUELGUAGE_SM5705 /
#                          STEP_CHARGING / USB_NOTIFY_LAYER / USB_NOTIFIER / USB_HOST_NOTIFY
#
#  搬完还要跑结构修补（power_supply 3.18→4.9 的模型差异）：
#    python3 tools/battery-fixes.py <内核树>
#
#  注意：MUIC 驱动（muic-universal 节点）与闪光灯驱动（sm5705-fled）还没搬，
#        它们不是电池栈编译的必需项；见 docs/NEXT.md。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
K="${1:-$ROOT/work/kernel-4.9}"
TB="$ROOT/work/samsung-msm8953-3.18.tar.gz"
D=android_kernel_samsung_msm8953-lineage-16.0

[ -d "$K" ] || { echo "找不到内核树: $K"; exit 1; }
[ -f "$TB" ] || { echo "找不到三星 3.18 源码包: $TB"; exit 1; }

echo "[1/4] 从 3.18 包里取文件"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
tar xzf "$TB" -C "$TMP" --wildcards \
	"$D/drivers/battery/*" \
	"$D/include/linux/battery/*" \
	"$D/include/linux/mfd/sm5705/*" \
	"$D/include/linux/muic/*" \
	"$D/include/linux/leds/*" \
	"$D/include/linux/sec_param.h" \
	"$D/include/linux/sec_jack.h" \
	"$D/include/linux/usb_notify.h" \
	"$D/include/linux/vbus_notifier.h" \
	"$D/include/linux/proportions.h" \
	"$D/include/linux/page-debug-flags.h" \
	"$D/include/linux/host_notify.h" \
	"$D/include/linux/external_notify.h" \
	"$D/include/linux/usb_hw_param.h" \
	"$D/include/linux/usblog_proc_notify.h" \
	"$D/include/linux/ccic/ccic_notifier.h" \
	"$D/drivers/usb/notify/*" \
	"$D/drivers/mfd/sm5705.c" \
	"$D/drivers/mfd/sm5705-irq.c" 2>/dev/null
S="$TMP/$D"

echo "[2/4] 拷贝（我们自己的目录直接覆盖；4.9 自带的头只补缺，绝不覆盖）"
mkdir -p "$K/drivers/battery" "$K/include/linux/battery" "$K/include/linux/mfd/sm5705" \
	 "$K/include/linux/muic" "$K/include/linux/leds" "$K/drivers/usb/notify" \
	 "$K/include/linux/ccic"
copy_own() {  # 目录：整目录**递归**同步（我们自己的东西；battery 下面还有 charger/ fuelgauge/ 子目录）
	mkdir -p "$2"; cp -af "$1"/. "$2"/ 2>/dev/null || true
}
copy_missing() {  # 文件：只在目标不存在时拷
	for f in "$@"; do
		b="$(basename "$f")"
		[ -e "$K/include/linux/$b" ] || cp -f "$f" "$K/include/linux/$b"
	done
}
for f in sec_battery.c sec_step_charging.c sm5705_charger.c sm5705_charger_oper.c sm5705_fuelgauge.c; do
	cp -f "$S/drivers/battery/$f" "$K/drivers/battery/"
done
copy_own "$S/include/linux/battery" "$K/include/linux/battery"
copy_own "$S/include/linux/mfd/sm5705" "$K/include/linux/mfd/sm5705"
copy_own "$S/include/linux/muic" "$K/include/linux/muic"
copy_own "$S/include/linux/leds" "$K/include/linux/leds"
copy_own "$S/drivers/usb/notify" "$K/drivers/usb/notify"
cp -f "$S/drivers/mfd/sm5705.c" "$S/drivers/mfd/sm5705-irq.c" "$K/drivers/mfd/"
copy_missing "$S/include/linux/sec_param.h" "$S/include/linux/sec_jack.h" \
	"$S/include/linux/usb_notify.h" "$S/include/linux/vbus_notifier.h" \
	"$S/include/linux/proportions.h" "$S/include/linux/page-debug-flags.h" \
	"$S/include/linux/host_notify.h" "$S/include/linux/external_notify.h" \
	"$S/include/linux/usb_hw_param.h" "$S/include/linux/usblog_proc_notify.h"
[ -e "$K/include/linux/ccic/ccic_notifier.h" ] || cp -f "$S/include/linux/ccic/ccic_notifier.h" "$K/include/linux/ccic/"

echo "[3/4] 最小 Makefile + 接线"
cat > "$K/drivers/battery/Makefile" <<'EOF'
# C7ROM: 只保留 C7 用得到的 Samsung 电池栈（SM5705），其余三星机型驱动不搬
obj-$(CONFIG_BATTERY_SAMSUNG)	+= sec_battery.o
obj-$(CONFIG_STEP_CHARGING)	+= sec_step_charging.o
obj-$(CONFIG_FUELGAUGE_SM5705)	+= sm5705_fuelgauge.o
obj-$(CONFIG_CHARGER_SM5705)	+= sm5705_charger.o sm5705_charger_oper.o
EOF
add_line() { grep -qF "$2" "$1" || printf '%s\n' "$2" >> "$1"; }
add_line "$K/drivers/Makefile"      'obj-$(CONFIG_BATTERY_SAMSUNG)	+= battery/'
add_line "$K/drivers/Kconfig"       'source "drivers/battery/Kconfig"'
add_line "$K/drivers/usb/Makefile"  'obj-$(CONFIG_USB_NOTIFY_LAYER)	+= notify/'
# MFD：SM5705 的寄存器访问（sm5705_read_reg 等）与 "sm5705-charger" 平台子设备都在这里
if ! grep -q "config MFD_SM5705" "$K/drivers/mfd/Kconfig"; then
cat >> "$K/drivers/mfd/Kconfig" <<'EOF'

config MFD_SM5705
	bool "Siliconmitus SM5705 IFPM Support (C7 PMIC: charger/USBLDO/RGB/dual-flash)"
	depends on I2C=y
	select MFD_CORE
	help
	  Say yes here to support the Siliconmitus SM5705 PMIC used on the
	  Galaxy C7 (SM-C7000).  This driver provides the regmap helpers
	  (sm5705_read_reg/sm5705_write_reg/sm5705_update_reg) and registers
	  the "sm5705-charger" platform cell that sm5705_charger.c binds to.
	  Ported from the Samsung msm8953 3.18 tree by the C7ROM project.
EOF
fi
add_line "$K/drivers/mfd/Makefile"   'obj-$(CONFIG_MFD_SM5705)	+= sm5705.o sm5705-irq.o'
add_line "$K/drivers/usb/Kconfig"   'source "drivers/usb/notify/Kconfig"'
for s in CONFIG_BATTERY_SAMSUNG=y CONFIG_CHARGER_SM5705=y CONFIG_FUELGAUGE_SM5705=y \
	 CONFIG_STEP_CHARGING=y CONFIG_USB_NOTIFY_LAYER=y CONFIG_USB_NOTIFIER=y CONFIG_USB_HOST_NOTIFY=y \
	 CONFIG_MFD_SM5705=y; do
	add_line "$K/arch/arm64/configs/c7ltechn_defconfig" "$s"
done

echo "[4/4] 结构修补（power_supply 模型：3.18 老式 → 4.9 desc+cfg）"
python3 "$ROOT/tools/battery-fixes.py" "$K"

cat <<EOF

完成。编译验证：
  cd $K && make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \\
      CROSS_COMPILE_ARM32=arm-linux-gnueabi- -j1 drivers/battery/
注意：defconfig 改动不影响已经在跑的构建（它用启动时的 .config 快照），
      要编它得先 scripts/config --file out/.config --enable ... && make olddefconfig。
EOF
