#!/bin/bash
# =============================================================================
#  audio-rt5659-setup.sh — C7 音频移植的"机械阶段"
#
#  用法: bash tools/audio-rt5659-setup.sh [内核树路径]      # 默认 work/kernel-4.9
#
#  它做什么（幂等）：
#    1. 从三星 3.18 包取 RT5659 机器驱动与它要的头，放进 4.9 的 techpack/audio/
#    2. 做 include 布局适配（3.18 的 sound/soc/msm/ 布局 → 4.9 techpack 布局）
#    3. 给 4.9 里"无提示"的 SND_SOC_RT5659 加一个可见开关（select 它），
#       这样 RT5659 codec 驱动（4.9 原生，component 版）能被编进来
#    4. 在 techpack 的 Kbuild / sdm450auto.conf 里**预留**机器驱动的挂载点，
#       但默认**不打开**（机器驱动还没做 API 迁移，详见 kernel/audio-rt5659-port-plan.md）
#
#  ★ 实测：做完第 1、2 步后，机器驱动还差 85 个错误（49 个 be_id、15 个 component/
#    dapm、15 个 mach_data 字段、5 个枚举/宏、1 个回调签名）。这份脚本只负责把那 85 个
#    "准备好"，真正的迁移步骤写在 kernel/audio-rt5659-port-plan.md 第 4 节。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
K="${1:-$ROOT/work/kernel-4.9}"
TB="$ROOT/work/samsung-msm8953-3.18.tar.gz"
D=android_kernel_samsung_msm8953-lineage-16.0
ASOC="$K/techpack/audio/asoc"

[ -d "$K" ] || { echo "找不到内核树: $K"; exit 1; }
[ -f "$TB" ] || { echo "找不到三星 3.18 源码包: $TB"; exit 1; }
[ -d "$ASOC" ] || { echo "这棵树没有 techpack/audio/asoc（音频布局不符）"; exit 1; }

echo "[1/4] 从 3.18 包取 RT5659 机器驱动与配套头"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
tar xzf "$TB" -C "$TMP" --wildcards \
	"$D/sound/soc/msm/msm8952_rt5659.c" \
	"$D/sound/soc/msm/msm-audio-pinctrl.h" \
	"$D/sound/soc/msm/msm-audio-pinctrl.c" \
	"$D/sound/soc/codecs/msm8x16-wcd.h" 2>/dev/null
S="$TMP/$D"
cp -f "$S/sound/soc/msm/msm8952_rt5659.c" "$ASOC/"
cp -f "$S/sound/soc/msm/msm-audio-pinctrl.h" "$ASOC/"
# msm_gpioset_* 的实现（机器驱动用它控制 I2S 引脚组）：4.9 techpack 里没有
cp -f "$S/sound/soc/msm/msm-audio-pinctrl.c" "$ASOC/"
cp -f "$S/sound/soc/codecs/msm8x16-wcd.h" "$ASOC/codecs/"
echo "    机器驱动 3809 行 + msm-audio-pinctrl.h + msm8x16-wcd.h"

echo "[2/4] include 布局适配（3.18 snd_soc → 4.9 techpack）"
python3 - "$K" <<'PY'
import sys, os
K = sys.argv[1]
targets = [
    "techpack/audio/asoc/msm8952_rt5659.c",
    "techpack/audio/asoc/msm-audio-pinctrl.h",
    "techpack/audio/asoc/codecs/msm8x16-wcd.h",
]
reps = [
    ("<sound/q6afe-v2.h>", "<dsp/q6afe-v2.h>"),
    ("<sound/q6core.h>", "<dsp/q6core.h>"),
    ('"qdsp6v2/msm-pcm-routing-v2.h"', '"msm-pcm-routing-v2.h"'),
    ('"../codecs/', '"codecs/'),
]
for t in targets:
    p = os.path.join(K, t)
    if not os.path.exists(p):
        continue
    s = open(p).read(); o = s
    for a, b in reps:
        s = s.replace(a, b)
    if s != o:
        open(p, "w").write(s)
        print("    适配:", t)
PY

echo "[3/4] 打开 RT5659 codec 驱动（4.9 里它是无提示 tristate，必须被 select）"
if ! grep -q "config SND_SOC_C7_RT5659" "$K/sound/soc/codecs/Kconfig"; then
	cat >> "$K/sound/soc/codecs/Kconfig" <<'EOF'

# C7ROM: Galaxy C7 (SM-C7000) 用的外部 codec 是 Realtek RT5659。
# 4.9 里 SND_SOC_RT5659 是**无提示**的 tristate（只被 SND_SOC_ALL_CODECS select），
# 所以这里加一个看得见的开关去 select 它。
config SND_SOC_C7_RT5659
	bool "Realtek RT5659 codec for Galaxy C7 (external I2C codec)"
	depends on I2C
	select SND_SOC_RT5659
	help
	  Say Y to build the RT5659 codec driver used by the Galaxy C7
	  (SM-C7000).  The machine driver on the techpack side links to its
	  DAIs (rt5659-aif1/2).  Added by the C7ROM project.
EOF
fi
add_line() { grep -qF "$2" "$1" || printf '%s\n' "$2" >> "$1"; }
add_line "$K/arch/arm64/configs/c7ltechn_defconfig" 'CONFIG_SND_SOC_C7_RT5659=y'

echo "[4/5] DTS：安装 audio dtsi（rt5659@1b + 覆盖 sound 节点 + 补出 i2c_6）"
cp -f "$ROOT/kernel/audio-3.18-source/msm8953-c7ltechn-audio.dtsi" "$K/arch/arm64/boot/dts/qcom/"
python3 - "$K" <<'PY2'
import sys, os
K = sys.argv[1]
dts = os.path.join(K, "arch/arm64/boot/dts/qcom/msm8953-c7ltechn.dts")
s = open(dts).read()
inc = '#include "msm8953-c7ltechn-audio.dtsi"'
if inc not in s:
    anchor = '#include "msm8953-c7ltechn-bhy.dtsi"'
    if anchor not in s:
        raise SystemExit("主 dts 里找不到 bhy include 锚点")
    open(dts, "w").write(s.replace(anchor, anchor + "\n" + inc, 1))
    print("    主 dts 已加 audio include")
PY2

echo "[5/5] 预留机器驱动的挂载点（默认关闭，迁移完成后再开）"
if ! grep -q "CONFIG_SND_SOC_RT5659_C7" "$K/techpack/audio/config/sdm450auto.conf" 2>/dev/null; then
	{
		echo ""
		echo "# C7ROM: Galaxy C7 的 RT5659 机器驱动（msm8952_rt5659.c）"
		echo "# 默认关闭：该文件还需要 3.18→4.9 的 API 迁移（85 个错误，见"
		echo "# kernel/audio-rt5659-port-plan.md）。迁移完成后把下面这行改成 =y。"
		echo "# CONFIG_SND_SOC_RT5659_C7=y"
	} >> "$K/techpack/audio/config/sdm450auto.conf"
fi
KB="$K/techpack/audio/asoc/Kbuild"
if ! grep -q "SND_SOC_RT5659_C7" "$KB"; then
	cat >> "$KB" <<'EOF'

# for Galaxy C7 (SM-C7000) RT5659 external codec sound card driver
ifdef CONFIG_SND_SOC_RT5659_C7
	# C7ROM: 必须挂到 machine_ext_dlkm（外部 codec 模块），不能往 MACHINE_OBJS 里加：
	#   1) 语义上 RT5659 就是外部 codec；
	#   2) Kbuild 里 `machine_dlkm-y := $(MACHINE_OBJS)` 是立即展开且出现在本文件更上面，
	#      在文件末尾再 `MACHINE_OBJS += ...` 是无效的（实测：对象根本没被编出来）；
	#   3) machine_ext_dlkm 的 INCS/EXTRA_CFLAGS 才带 techpack/audio/include，
	#      否则 <dsp/q6afe-v2.h> 找不到。
	machine_ext_dlkm-y += msm8952_rt5659.o
	# 该文件用到 codecs/msm8x16-wcd.h 里被 CONFIG_SND_SOC_MSM8X16_RT5659 包住的
	# mach_data 扩展字段（codec / rt5659_ext_clk / codec_irq_gpio / codec_ear_bias）。
	# 头文件结构定义不动，用 per-file ccflags 让它们可见。
	CFLAGS_msm8952_rt5659.o += -DCONFIG_SND_SOC_MSM8X16_RT5659
endif
EOF
fi

cat <<EOF

完成（机械阶段）。现在的状态：
  * techpack/audio/asoc/msm8952_rt5659.c 已在树里，但**没有**挂进构建
  * include 已适配到 4.9 techpack 布局
  * RT5659 codec 驱动开关已就绪（CONFIG_SND_SOC_C7_RT5659=y）

下一步（详见 kernel/audio-rt5659-port-plan.md 第 4 节）：
  1. 清 be_id（49 处，照 techpack/audio/asoc/msm8952-dai-links.c 写）
  2. 补 msm8916_asoc_mach_data 的 4 个字段（15 处）
  3. 对枚举/寄存器宏（5 处）
  4. component 迁移（widget->codec / codec->dapm，15 处 + 连带）
  把 sdm450auto.conf 里 CONFIG_SND_SOC_RT5659_C7=y 打开即可开始编译循环：
  cd $K && make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \\
       CROSS_COMPILE_ARM32=arm-linux-gnueabi- -j1 techpack/audio/asoc/msm8952_rt5659.o
EOF
