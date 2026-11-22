#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio-rt5659-fixes.py — 把三星 3.18 的 RT5659 机器驱动（Galaxy C7）
`techpack/audio/asoc/msm8952_rt5659.c` 迁到 Linux 4.9 的 techpack ASoC 框架上。
**幂等**，可重复运行。

  用法: python3 tools/audio-rt5659-fixes.py [内核树路径]   # 默认 work/kernel-4.9

前置：先跑 `tools/audio-rt5659-setup.sh`（把 3.18 的 .c/.h 放进树里并适配 include）。
本脚本负责剩下的 API 代差。参照物是**同平台 4.9 原生**的
`techpack/audio/asoc/msm8952-dai-links.c`（以及 msm8952.c / msm8909.c）：
它们用同样的写法在 4.9 上跑通，所以凡是能做"和原生一模一样"的地方就照抄。

七节（对应编译器报错分类）：

  [1] Kbuild：给 msm8952_rt5659.o 加 -DCONFIG_SND_SOC_MSM8X16_RT5659
      —— 三星把 mach_data 的 4 个扩展字段（codec / rt5659_ext_clk /
      codec_irq_gpio / codec_ear_bias）包在这个宏里，4.9 的 sdm450 配置没开它。
      按需求"不动头文件里的结构定义"，用 ccflags 打开（15 个报错）。

  [2] FE DAI 枚举代差（4 个）：3.18 的 msm-pcm-routing-v2.h 有
      CS_VOICE / VOICE2 / VOLTE / VOWLAN，4.9 的删掉了。4.9 原生
      msm8952-dai-links.c 第 24-30 行用一段**本地 enum**（CS_VOICE=39）补回来，
      这里照抄，保证 .id 数值与 4.9 原生机器驱动一致。

  [3] `struct snd_soc_dai_link` 4.9 把 3.18 高通私有的 `be_id` 改名成 `id`
      （`->be_id` → `->id`、`.be_id =` → `.id =`，49 个报错）。
      4.9 的 routing 驱动读的正是 `rtd->dai_link->id`
      （msm-pcm-routing-v2.c:20488 等），所以这是纯改名，语义不变。

  [4] DAPM context 4.9 挪进 component：`codec->dapm` → `codec->component.dapm`
      （8 个报错 + samsung-jack 分支里 1 处）。

  [5] `struct snd_soc_dapm_widget` 4.9 删掉了 `codec` 成员（8 个报错）：
      - 取卡：`w->codec->component.card` → `w->dapm->card`
      - 取 codec：`w->codec` → `snd_soc_dapm_to_codec(w->dapm)`
        （4.9 原生 msm8952.c:178/225 就是这么写的）

  [6] 寄存器宏代差：3.18 的 `RT5659_MICBIAS1` 在 4.9 里叫 `RT5659_MICBIAS_1`
      （techpack/audio/asoc/codecs/rt5659.h:164，值都是 0x0093）。

  [7] 回调签名代差：4.9 的 `struct wcd_mbhc_config.swap_gnd_mic` 是
      `bool (*)(struct snd_soc_codec *, bool)`（codecs/wcd-mbhc-v2.h:427），
      3.18 只有 codec 一个参数。给函数补上 `bool active`；实现保持原样不动
      （4.9 原生 msm8952.c:395 的实现同样忽略 active），行为不变。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "work", "kernel-4.9")

C = os.path.join(K, "techpack/audio/asoc/msm8952_rt5659.c")
KBUILD = os.path.join(K, "techpack/audio/asoc/Kbuild")

# 挂载块：必须挂 machine_ext_dlkm（见 fix_kbuild_ccflags 的注释）
KBUILD_BLOCK = """# for Galaxy C7 (SM-C7000) RT5659 external codec sound card driver
ifdef CONFIG_SND_SOC_RT5659_C7
	# C7ROM: 必须挂到 machine_ext_dlkm（外部 codec 模块），不能往 MACHINE_OBJS 里加：
	#   1) 语义上 RT5659 就是外部 codec；
	#   2) Kbuild 里 `machine_dlkm-y := $(MACHINE_OBJS)` 是立即展开且出现在本文件更上面，
	#      在文件末尾再 `MACHINE_OBJS += ...` 是无效的（实测：对象根本没被编出来）；
	#   3) machine_ext_dlkm 的 INCS/EXTRA_CFLAGS 才带 techpack/audio/include，
	#      否则 <dsp/q6afe-v2.h> 找不到。
	machine_ext_dlkm-y += msm8952_rt5659.o
	# msm_gpioset_initialize/activate/suspend + msm_get_gpioset_index 的实现
	# （三星的 audio pinctrl 助手，304 行；4.9 techpack 里没有，vmlinux 链接会 undefined）
	machine_ext_dlkm-y += msm-audio-pinctrl.o
	# 该文件用到 codecs/msm8x16-wcd.h 里被 CONFIG_SND_SOC_MSM8X16_RT5659 包住的
	# mach_data 扩展字段（codec / rt5659_ext_clk / codec_irq_gpio / codec_ear_bias）。
	# 头文件结构定义不动，用 per-file ccflags 让它们可见。
	CFLAGS_msm8952_rt5659.o += -DCONFIG_SND_SOC_MSM8X16_RT5659
endif
"""

# 3.18 的 .c 里 include 已被 setup 适配成 techpack 布局，拿它当锚点
INCLUDE_ANCHOR = '#include "codecs/rt5659.h"\n'

# 4.9 原生 msm8952-dai-links.c:25-30 的同一段补丁
FE_ENUM = """
/*
 * C7ROM: 3.18 -> 4.9 前端 DAI 枚举代差。
 * 三星 3.18 的 msm-pcm-routing-v2.h 里有 CS_VOICE / VOICE2 / VOLTE / VOWLAN
 * 四个前端 DAI；4.9 的 techpack/audio/asoc/msm-pcm-routing-v2.h 把它们删了
 * （只剩 *_STUB 之类的替代名字）。4.9 同平台原生机器驱动 msm8952-dai-links.c
 * 用下面这段本地 enum 把旧名字补回来（见该文件第 24-30 行），这里照抄同样的
 * 定义，保证下面各 dai_link 的 .id 数值语义与 4.9 原生驱动完全一致。
 */
enum {
\tMSM_FRONTEND_DAI_CS_VOICE = 39,
\tMSM_FRONTEND_DAI_VOICE2,
\tMSM_FRONTEND_DAI_VOLTE,
\tMSM_FRONTEND_DAI_VOWLAN,
};
"""


def report(msg):
    print("  " + msg)


def read(p):
    with open(p) as f:
        return f.read()


def write(p, txt):
    with open(p, "w") as f:
        f.write(txt)


# ---------------------------------------------------------------------------
def fix_kbuild_ccflags():
    """[1] Kbuild：把机器驱动挂到 machine_ext_dlkm（外部 codec 模块）并打开
    mach_data 的 RT5659 扩展字段。

    ★ 两个坑（都实测踩过）：
      a) 往 `MACHINE_OBJS` 里加是**无效**的 —— 本文件上面已经有
         `machine_dlkm-y := $(MACHINE_OBJS)`（立即展开），末尾再 += 不会进模块，
         对象根本不会被编。正确做法是直接 `machine_ext_dlkm-y +=`。
      b) 直接 `make techpack/audio/asoc/xxx.o` 会因为拿不到 `EXTRA_CFLAGS/INCS`
         （techpack/audio/include）而找不到 <dsp/q6afe-v2.h>；要编整个
         `techpack/audio/` 目录才是真实路径。
    """
    print("[1/8] Kbuild：挂 machine_ext_dlkm + -DCONFIG_SND_SOC_MSM8X16_RT5659")
    txt = read(KBUILD)
    marker = "# for Galaxy C7 (SM-C7000) RT5659 external codec sound card driver"
    if marker not in txt:
        report("!! Kbuild 里没有 C7 挂载点（先跑 audio-rt5659-setup.sh）")
        return 0
    i = txt.find(marker)
    j = txt.find("endif\n", i)
    if j < 0:
        report("!! Kbuild 挂载块不完整")
        return 0
    j += len("endif\n")
    cur = txt[i:j]
    if ("machine_ext_dlkm-y += msm8952_rt5659.o" in cur
            and "machine_ext_dlkm-y += msm-audio-pinctrl.o" in cur):
        report("已是 machine_ext_dlkm 挂法，跳过")
        return 0
    txt = txt[:i] + KBUILD_BLOCK + txt[j:]
    write(KBUILD, txt)
    report("旧写法(MACHINE_OBJS) -> machine_ext_dlkm-y += msm8952_rt5659.o")
    return 1


def fix_fe_dai_enum():
    """[2] 补回 4.9 删掉的 4 个前端 DAI 名字（照抄 4.9 原生驱动）。"""
    print("[2/8] FE DAI 枚举：补 CS_VOICE/VOICE2/VOLTE/VOWLAN")
    txt = read(C)
    if "MSM_FRONTEND_DAI_CS_VOICE = 39" in txt:
        report("已存在，跳过")
        return 0
    if INCLUDE_ANCHOR not in txt:
        report("!! 找不到 include 锚点，跳过")
        return 0
    txt = txt.replace(INCLUDE_ANCHOR, INCLUDE_ANCHOR + FE_ENUM, 1)
    write(C, txt)
    report("已插入本地 enum（CS_VOICE=39，与 msm8952-dai-links.c 一致）")
    return 1


def fix_be_id():
    """[3] 4.9 把 dai_link 的 be_id 改名成 id。"""
    print("[3/8] dai_link：.be_id / ->be_id 改名成 4.9 的 .id / ->id")
    txt = read(C)
    n1 = txt.count(".be_id =")
    n2 = txt.count("->be_id")
    if not n1 and not n2:
        report("已改名，跳过")
        return 0
    txt = txt.replace(".be_id =", ".id =")
    txt = txt.replace("->be_id", "->id")
    write(C, txt)
    report("字段改名 %d 处（.be_id=%d, ->be_id=%d）" % (n1 + n2, n1, n2))
    return n1 + n2


def fix_codec_dapm():
    """[4] DAPM context 4.9 挪进 component。"""
    print("[4/8] codec->dapm → codec->component.dapm")
    txt = read(C)
    n = txt.count("codec->dapm")
    if not n:
        report("已迁移，跳过")
        return 0
    txt = txt.replace("codec->dapm", "codec->component.dapm")
    write(C, txt)
    report("迁移 %d 处（含 pdata->codec->dapm 1 处）" % n)
    return n


def fix_widget_codec():
    """[5] widget 4.9 删掉了 codec 成员。"""
    print("[5/8] w->codec → w->dapm->card / snd_soc_dapm_to_codec(w->dapm)")
    txt = read(C)
    n1 = txt.count("w->codec->component.card")
    # 先换长模式，否则会被短模式先吃掉
    txt = txt.replace("w->codec->component.card", "w->dapm->card")
    n2 = txt.count("w->codec")
    if not n1 and not n2:
        report("已迁移，跳过")
        return 0
    txt = txt.replace("w->codec", "snd_soc_dapm_to_codec(w->dapm)")
    write(C, txt)
    report("card %d 处，codec %d 处" % (n1, n2))
    return n1 + n2


def fix_rt5659_micbias():
    """[6] 3.18 的 RT5659_MICBIAS1 → 4.9 的 RT5659_MICBIAS_1。"""
    print("[6/8] 寄存器宏 RT5659_MICBIAS1 → RT5659_MICBIAS_1")
    txt = read(C)
    n = txt.count("RT5659_MICBIAS1")
    if not n:
        report("已改名，跳过")
        return 0
    txt = txt.replace("RT5659_MICBIAS1", "RT5659_MICBIAS_1")
    write(C, txt)
    report("改名 %d 处（值同为 0x0093）" % n)
    return n


def fix_swap_gnd_mic():
    """[7] 4.9 的 swap_gnd_mic 多一个 bool active 参数。"""
    print("[7/8] swap_gnd_mic 回调签名补 bool active")
    txt = read(C)
    old_decl = "static bool msm8952_swap_gnd_mic(struct snd_soc_codec *codec);"
    old_def = "static bool msm8952_swap_gnd_mic(struct snd_soc_codec *codec)\n{"
    new_decl = (
        "/* C7ROM: 4.9 的 wcd_mbhc_config.swap_gnd_mic 原型多一个 bool active\n"
        " * (codecs/wcd-mbhc-v2.h)，补上；实现同 4.9 原生 msm8952.c 一样忽略它。 */\n"
        "static bool msm8952_swap_gnd_mic(struct snd_soc_codec *codec, bool active);"
    )
    new_def = (
        "/* C7ROM: 同上，补 4.9 的 bool active 形参；行为与 3.18 实现一致\n"
        " * （只翻转 us_euro_gpio，不看 active —— 4.9 原生 msm8952.c:395 也这样）。 */\n"
        "static bool msm8952_swap_gnd_mic(struct snd_soc_codec *codec, bool active)\n{"
    )
    n = 0
    if old_decl in txt:
        txt = txt.replace(old_decl, new_decl, 1)
        n += 1
    if old_def in txt:
        txt = txt.replace(old_def, new_def, 1)
        n += 1
    if not n:
        report("已改，跳过")
        return 0
    write(C, txt)
    report("签名修改 %d 处（声明 + 定义）" % n)
    return n


# ---------------------------------------------------------------------------
def fix_link_and_warnings():
    """[8] 链接期与告警：4.9 树里没有 msm8x16-wcd.c，所以
    `msm8x16_wcd_mclk_enable()` 全树只有 extern 声明（codecs/msm8x16-wcd.h:356）
    没有定义 —— 编译能过，模块链接一定 undefined。RT5659 走的是外部 MCLK，
    本文件的 `msm8952_rt5659_set_mclk()` 才是对应实现，4 处调用全部改过去。

    同时修三件"顺手能修的真 bug / 告警"：
      a) `is_us_eu_switch_gpio_support()` 与 4.9 原生 msm8952.c:434 **重名**
         （两个模块都链进 built-in.o → multiple definition）。本文件里只有
         3534 一处调用，改 static 即可。
      b) 1236 行 `if (atomic_dec_return(...) == 0)` 缺花括号，导致后面的
         `if (ret)` 实际落在 if 之外（-Wmisleading-indentation 指出的逻辑 bug）。
         按缩进本意补花括号。
      c) `def_msm8952_wcd_mbhc_cal()` 未被使用（-Wunused-function），加
         __maybe_unused（该函数在 CONFIG_SAMSUNG_JACK 路径下才用）。
      d) `msm8952_rt5659_set_mclk()` 里对 `pdata->rt5659_ext_clk` 没有判空，
         时钟没拿到会 NULL 解引用；补一个防御性检查。
    """
    print("[8/8] 链接期：msm8x16_wcd_mclk_enable -> msm8952_rt5659_set_mclk + 3 处告警/重名")
    txt = read(C)
    n = 0

    # a) 重名 -> static
    if "static int is_us_eu_switch_gpio_support(" not in txt:
        new = txt.replace("\nint is_us_eu_switch_gpio_support(struct platform_device *pdev,",
                          "\nstatic int is_us_eu_switch_gpio_support(struct platform_device *pdev,", 1)
        if new != txt:
            txt = new; n += 1

    # b) 缺花括号
    old_b = ("\t\tif (atomic_dec_return(&supply->ref) == 0)\n"
             "\t\t\tret = regulator_disable(supply->supply);\n"
             "\t\t\tif (ret)\n"
             "\t\t\t\tdev_err(w->dapm->card->dev,\n"
             "\t\t\t\t\t\"%s: Failed to disable wsa switch supply\\n\",\n"
             "\t\t\t\t\t__func__);\n")
    new_b = ("\t\tif (atomic_dec_return(&supply->ref) == 0) {\n"
             "\t\t\tret = regulator_disable(supply->supply);\n"
             "\t\t\tif (ret)\n"
             "\t\t\t\tdev_err(w->dapm->card->dev,\n"
             "\t\t\t\t\t\"%s: Failed to disable wsa switch supply\\n\",\n"
             "\t\t\t\t\t__func__);\n"
             "\t\t}\n")
    if old_b in txt:
        txt = txt.replace(old_b, new_b, 1); n += 1

    # c) 未使用函数
    if "static void __maybe_unused *def_msm8952_wcd_mbhc_cal(void)" not in txt:
        new = txt.replace("\nstatic void *def_msm8952_wcd_mbhc_cal(void)",
                          "\nstatic void __maybe_unused *def_msm8952_wcd_mbhc_cal(void)", 1)
        if new != txt:
            txt = new; n += 1

    # d) MCLK：4 处换成 RT5659 自己的外部 MCLK 实现
    reps = [
        ("msm8x16_wcd_mclk_enable(snd_soc_dapm_to_codec(w->dapm), 0, true)",
         "msm8952_rt5659_set_mclk(w->dapm->card, 0) /* C7ROM: 4.9 无 msm8x16-wcd.c，用 RT5659 外部 MCLK */"),
        ("msm8x16_wcd_mclk_enable(codec, 1, true)",
         "msm8952_rt5659_set_mclk(codec->component.card, 1) /* C7ROM: 同上 */"),
        ("msm8x16_wcd_mclk_enable(codec, 0, true)",
         "msm8952_rt5659_set_mclk(codec->component.card, 0) /* C7ROM: 同上 */"),
    ]
    for a, b in reps:
        if a in txt:
            n += txt.count(a)
            txt = txt.replace(a, b)

    # e) set_mclk 判空
    if "if (!pdata || !pdata->rt5659_ext_clk)" not in txt:
        anchor = ("\tstruct msm8916_asoc_mach_data *pdata = snd_soc_card_get_drvdata(card);\n"
                  "\tint ret;\n")
        guard = (anchor +
                 "\n\t/* C7ROM: 防御 —— DTS 里没给 ext-mclk 时不要 NULL 解引用 */\n"
                 "\tif (!pdata || !pdata->rt5659_ext_clk) {\n"
                 "\t\tdev_err(card->dev, \"%s: no ext-mclk clock\\n\", __func__);\n"
                 "\t\treturn;\n"
                 "\t}\n")
        if anchor in txt:
            txt = txt.replace(anchor, guard, 1); n += 1

    if n:
        write(C, txt)
    report("共 %d 处改动" % n)
    return n



def main():
    if not os.path.isdir(K):
        raise SystemExit("找不到内核树: %s" % K)
    if not os.path.isfile(C):
        raise SystemExit("找不到机器驱动: %s（先跑 tools/audio-rt5659-setup.sh）" % C)
    print("内核树: %s\n" % K)
    total = 0
    total += fix_kbuild_ccflags()
    total += fix_fe_dai_enum()
    total += fix_be_id()
    total += fix_codec_dapm()
    total += fix_widget_codec()
    total += fix_rt5659_micbias()
    total += fix_swap_gnd_mic()
    total += fix_link_and_warnings()
    print("\n完成：本次共 %d 处改动（幂等，可重复运行）" % total)


if __name__ == "__main__":
    main()
