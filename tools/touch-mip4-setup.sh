#!/bin/bash
# =============================================================================
#  touch-mip4-setup.sh — 把主线 MELFAS MIP4 触摸驱动装进 4.9 树（MMS449 的替代方案）
#
#  用法: bash tools/touch-mip4-setup.sh [内核树路径]      # 默认 work/kernel-4.9
#
#  背景：C7 的触摸是 MELFAS MMS449，公开三星树里没有对应驱动（已多来源核实）；
#        而 MMS449 属 MELFAS MIP4 协议族，主线 Linux 有完整驱动。
#        取的是 **v4.14 版**（MIP 4.0 Rev 5.4，1631 行，compatible "melfas,mip4_ts"）：
#        master 版用了 __free()/guard() 等新 API，在 4.9 上 31 个错误；v4.14 版 0 错误。
#        详见 kernel/melfas-mip4-mainline/README.md。
#
#  与补丁的关系：本脚本 = 补丁 0011（kernel/patches/0011-*.patch）的等价实现，
#        两者产出的驱动/DTS/defconfig 内容逐字节一致（实测）。补丁是权威版本；
#        本脚本用于"不经 git am 也能装好"和幂等重跑。
#
#  做三件事（幂等）：
#    1. 拷贝驱动源码（mido 树原本自带 Rev 4.6，这里覆盖成 Rev 5.4）
#    2. 挂 Kconfig / Makefile（mido 树已有同名条目，会跳过）
#    3. 在 c7ltechn_defconfig 里打开
#  注意：DTS 的 compatible / ce-gpios 改动由补丁 0011 负责，本脚本不动 DTS。
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
K="${1:-$ROOT/work/kernel-4.9}"
SRC="$ROOT/kernel/melfas-mip4-mainline/melfas_mip4.c"
DST_DIR="$K/drivers/input/touchscreen"
DST="$DST_DIR/melfas_mip4.c"

[ -d "$K" ] || { echo "找不到内核树: $K"; exit 1; }
[ -f "$SRC" ] || { echo "找不到驱动源码: $SRC"; exit 1; }

echo "[1/3] 拷贝驱动 -> $DST"
cp -f "$SRC" "$DST"

echo "[2/3] 4.9 适配修补"
# 主线用 linux/unaligned.h，4.9 里这个头叫 asm/unaligned.h
if grep -q "linux/unaligned.h" "$DST"; then
  sed -i 's|#include <linux/unaligned.h>|#include <asm/unaligned.h>|' "$DST"
  echo "    linux/unaligned.h -> asm/unaligned.h"
fi

echo "[2/3] 挂 Kconfig / Makefile"
if ! grep -q "TOUCHSCREEN_MELFAS_MIP4" "$DST_DIR/Kconfig"; then
cat >> "$DST_DIR/Kconfig" <<'EOF'

config TOUCHSCREEN_MELFAS_MIP4
	tristate "MELFAS MIP4 Touchscreen (mainline driver, used for C7's MMS449)"
	depends on I2C
	help
	  Say Y here if you have a MELFAS MIP4 based touchscreen controller.

	  This is the upstream Linux driver, used by the C7ROM project as the
	  substitute for Samsung's missing 'melfas,mms_ts' driver on the
	  Galaxy C7 (SM-C7000).  See kernel/melfas-mip4-mainline/README.md.
EOF
fi
if ! grep -q "melfas_mip4" "$DST_DIR/Makefile"; then
	printf 'obj-$(CONFIG_TOUCHSCREEN_MELFAS_MIP4)\t+= melfas_mip4.o\n' >> "$DST_DIR/Makefile"
fi

echo "[3/3] 打开开关（c7ltechn_defconfig）"
DEF="$K/arch/arm64/configs/c7ltechn_defconfig"
if [ -f "$DEF" ] && ! grep -q "TOUCHSCREEN_MELFAS_MIP4" "$DEF"; then
	printf 'CONFIG_TOUCHSCREEN_MELFAS_MIP4=y\n' >> "$DEF"
fi

echo
echo "完成。接着编译验证（注意：需等全量构建结束后再跑）："
echo "  cd $K && make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \\"
echo "      CROSS_COMPILE_ARM32=arm-linux-gnueabi- drivers/input/touchscreen/melfas_mip4.o"
