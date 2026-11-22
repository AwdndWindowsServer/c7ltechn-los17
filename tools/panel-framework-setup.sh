#!/bin/bash
# =============================================================================
#  panel-framework-setup.sh — 把三星面板框架装进 4.9 内核树（C7ROM 面板移植 ① ② 步）
#
#  用法: bash tools/panel-framework-setup.sh [内核树路径]    # 默认 work/kernel-4.9
#
#  做四件事（全部幂等）：
#    1. 把 kernel/panel-3.18-source/（三星面板框架 + C7 面板）复制进
#       <内核树>/drivers/video/fbdev/msm/samsung/
#       （注意：4.9 的显示驱动在 drivers/video/fbdev/msm/，不是 3.18 的 video/msm/mdss/）
#    2. 跑 tools/panel-framework-fixes.py 打接口修补（每条都对应一个真实编译错误）
#    3. 从三星 3.18 tarball 补缺的头文件
#    4. 挂 Makefile / Kconfig，并把开关写进 c7ltechn_defconfig
#
#  当前进度（详见 kernel/panel-port-plan.md）：
#    框架 11 个 .c 里 7 个已编译通过（其余 4 个由 config 关闭）；
#    还差三星对 mdss 核心文件的改造（mdss_dsi.c/mdss_fb.c 里的 samsung_* 挂钩与
#    mdss_samsung_parse_dcs_cmds / mdss_samsung_panel_cmd_read 的实现）。
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
K="${1:-$ROOT/work/kernel-4.9}"
SAMSUNG_SRC="${SAMSUNG_SRC:-$ROOT/kernel/panel-3.18-source-bak2}"   # bak-2 分支的框架与 C7 面板是同一修订版（lineage-16.0 的框架过旧）
TB="$ROOT/work/samsung-msm8953-3.18.tar.gz"
D=android_kernel_samsung_msm8953-lineage-16.0
DST="$K/drivers/video/fbdev/msm/samsung"

[ -d "$K" ] || { echo "找不到内核树: $K"; exit 1; }
[ -d "$SAMSUNG_SRC" ] || { echo "找不到面板源料: $SAMSUNG_SRC"; exit 1; }

echo "[1/4] 复制三星面板框架与 C7 面板 -> $DST"
mkdir -p "$DST"
cp -a "$SAMSUNG_SRC/." "$DST/"

echo "[2/4] 清理 Makefile 里指向不存在目录的 obj-y"
# bak-2 的 samsung/Makefile 用 obj-y 列了十几个面板目录，我们只保留了 C7 的两个，
# 那些不存在的目录会让 kbuild 报 "No rule to make target .../Makefile" 而中断整树构建。
python3 - "$K/drivers/video/fbdev/msm/samsung/Makefile" <<'PYEOF'
import os, re, sys
p = sys.argv[1]
if not os.path.exists(p):
    sys.exit(0)
d = os.path.dirname(p)
lines = open(p, encoding="utf-8", errors="replace").read().split("\n")
keep, dropped = [], []
for l in lines:
    m = re.search(r'\+=\s*([A-Za-z0-9_./-]+/)\s*$', l)
    if m and not os.path.isdir(os.path.join(d, m.group(1).rstrip('/'))):
        dropped.append(m.group(1)); continue
    keep.append(l)
if dropped:
    open(p, "w", encoding="utf-8").write("\n".join(keep))
    print("    移除 %d 行指向不存在目录的 obj-y" % len(dropped))
PYEOF

echo "[2/4] 打接口修补"
python3 "$ROOT/tools/panel-framework-fixes.py" "$K"
# 核心侧：移植 2 个三星函数 + 让核心回头调用三星框架（面板挂钩）
python3 "$ROOT/tools/panel-core-hooks.py" "$K"

echo "[3/4] 从三星 3.18 tarball 补缺的头文件"
if [ -f "$TB" ]; then
  for h in linux/self_display/self_display.h linux/sec_debug.h linux/sec_debug_arm.h linux/sec_debug_arm64.h; do
    dst="$K/include/$h"
    [ -f "$dst" ] && continue
    if tar tzf "$TB" "$D/include/uapi/$h" >/dev/null 2>&1; then
      mkdir -p "$(dirname "$dst")"; tar xzOf "$TB" "$D/include/uapi/$h" > "$dst"; echo "    补 $h (uapi)"
    elif tar tzf "$TB" "$D/include/$h" >/dev/null 2>&1; then
      mkdir -p "$(dirname "$dst")"; tar xzOf "$TB" "$D/include/$h" > "$dst"; echo "    补 $h"
    else
      echo "    ! 三星树里也没有 $h，需要 shim（见 panel-port-plan.md）"
    fi
  done
else
  echo "    找不到 $TB，跳过"
fi

echo "[4/4] 挂 Makefile / Kconfig，并写入 c7ltechn_defconfig"
add_line() {
  local f="$1" l="$2"
  [ -f "$f" ] || return 0
  grep -qF "$l" "$f" || printf '%s\n' "$l" >> "$f"
}
# ★ 三星那份 Makefile 有个坑：它把 "C5 PRO panel" 那行也写成了
#   obj-$(CONFIG_PANEL_S6E3FA3_AMS598KH01_FHD) += S6E3FA3_AMS520MV01/
#   —— 和 C7 用的面板**共用同一个配置符号**，于是两个面板目录同时编，
#   链接时 hbm_interpolation_table 之类的全局符号重复定义（实测报错）。
#   所以我们直接写一份最小 Makefile：只留框架公共对象 + C7 面板目录。
cat > "$DST/Makefile" <<'EOF'
#
# C7ROM 最小面板 Makefile（覆盖三星原版）
#
# 三星原版把所有机型的 panel 目录都用 obj-$(CONFIG_PANEL_xxx) 挂着，
# 但 AMS598KH01（C7）与 AMS520MV01（C5 Pro）被错写成同一个配置符号，
# 一旦打开就会同时编两个面板，链接期全局符号（hbm_interpolation_table 等）重复定义。
# 这里只保留 C7 需要的：4 个框架公共对象 + C7 面板目录。
#
obj-y += ss_dsi_panel_common.o
obj-y += ss_dsi_mdnie_lite_common.o
obj-y += ss_dsi_smart_dimming_common.o
obj-y += ss_regulator_common.o
obj-$(CONFIG_SAMSUNG_DEBUG_DISPLAY) += dlog.o
obj-$(CONFIG_DISPLAY_USE_INFO) += ss_dpui_common.o

# C7 (SM-C7000) 面板：S6E3FA3 AMS598KH01 FHD
obj-$(CONFIG_PANEL_S6E3FA3_AMS598KH01_FHD) += S6E3FA3_AMS598KH01/
EOF
add_line "$K/drivers/video/fbdev/msm/Makefile" 'obj-$(CONFIG_FB_MSM_MDSS_SAMSUNG)	+= samsung/'
if ! grep -q 'samsung/Kconfig' "$K/drivers/video/fbdev/msm/Kconfig"; then
  cat >> "$K/drivers/video/fbdev/msm/Kconfig" <<'EOF'

# C7ROM: 三星面板框架与 C7 面板
source "drivers/video/fbdev/msm/samsung/Kconfig"

config PANEL_S6E3FA3_AMS598KH01_FHD
	bool "Samsung S6E3FA3 AMS598KH01 FHD panel (Galaxy C7)"
	depends on FB_MSM_MDSS_SAMSUNG
	default n

config PANEL_S6E3FA3_AMS568HN31_FHD
	bool "Samsung S6E3FA3 AMS568HN31 FHD panel (Galaxy C7 alt)"
	depends on FB_MSM_MDSS_SAMSUNG
	default n
EOF
fi
add_line "$K/arch/arm64/configs/c7ltechn_defconfig" 'CONFIG_FB_MSM_MDSS_SAMSUNG=y'
add_line "$K/arch/arm64/configs/c7ltechn_defconfig" 'CONFIG_PANEL_S6E3FA3_AMS598KH01_FHD=y'

echo
echo "完成。接着编译："
echo "  cd $K && make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \\"
echo "      CROSS_COMPILE_ARM32=arm-linux-gnueabi- c7ltechn_defconfig"
echo "  make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \\"
echo "      CROSS_COMPILE_ARM32=arm-linux-gnueabi- drivers/video/fbdev/msm/samsung/"
