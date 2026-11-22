# 音频移植方案（C7 → Linux 4.9 的 techpack 音频）

> 这份文件是**实测**出来的工程量，不是估计。测量方法：把三星那份机器驱动放进 4.9 树里，
> 用构建系统**真实的编译命令**（取自 `out/techpack/audio/asoc/.msm8952-dai-links.o.cmd`）编译它，
> 数出来的错误。

## 1. 结论

C7 的音频**不是 WCD9335**，而是 **RT5659**（外部 I2C codec，`sound` 节点 compatible
`qcom,msm8952-rt5659-audio-codec`，三星机器驱动 `sound/soc/msm/msm8952_rt5659.c`，**3809 行**）。
4.9 树里的音频已经全部搬到 **`techpack/audio/`**，而且对 msm8953 是**开着的**：

| 4.9 已有 | 说明 |
|---|---|
| `CONFIG_SND_SOC_SDM450=y` → `techpack/audio/asoc/msm8952.o` | SDM450/msm8953 **内部 codec** 机器驱动 |
| `CONFIG_SND_SOC_EXT_CODEC_SDM450=y` → `msm8952-slimbus.o` + `msm8952-dai-links.o` | **外部 codec** 机器驱动（针对 WCD9335/slimbus） |
| `CONFIG_SND_SOC_WCD9335` / QDSP6V2 / AFE v2 / msm-pcm-routing | 完整 DSP 与前端链路 |
| `sound/soc/codecs/rt5659.c`（legacy 路径，DAI `rt5659-aif1..3`，I2C `realtek,rt5659`） | ★ **RT5659 codec 驱动 4.9 树里本来就有**，只是没被编译 |

**4.9 techpack 里 RT5659 支持为零**（外部 codec 只做 WCD9335），所以缺的是**机器驱动**。

## 2. 实测错误面：85 个错误，5 类

include 层面修完后（见第 3 节），真实报错 **85 个**，全部集中在机器驱动里：

| # | 错误 | 数量 | 性质 / 修法 |
|---|---|---|---|
| 1 | `'struct snd_soc_dai_link' has no member named 'be_id'` | **49** | 3.18 的 dai_link 用 `be_id` 标后端；4.9 没有这个成员。修法：删掉 `.be_id = ...`，后端 DAI 改为按 `dai_name` 匹配（照抄同平台的 `msm8952-dai-links.c` 写法） |
| 2 | `'struct snd_soc_dapm_widget' has no member named 'codec'` / `'struct snd_soc_codec' has no member named 'dapm'` | **15** | ★ **这是最硬的一类**：4.9 的 ASoC 已经没有 `struct snd_soc_codec`，DAPM 全部走 **component**（`snd_soc_component`）。这 15 处要按 component API 重写 |
| 3 | `'struct msm8916_asoc_mach_data' has no member named 'rt5659_ext_clk' / 'codec_irq_gpio' / 'codec' / 'codec_ear_bias'` | **15** | 三星的 mach_data 比 4.9 多几个字段。修法：在 4.9 的 `msm8x16-wcd.h`（或我们自己的头）里补这几个字段，或改用它已有的等价字段 |
| 4 | `'MSM_FRONTEND_DAI_VOLTE' / 'VOICEN' / 'CS_VOICE' / 'VOWLAN'` 未声明 + `RT5659_MICBIAS1` 未声明 | **5** | 枚举/寄存器宏的代差：4.9 的 `msm-pcm-routing-v2.h` 前端 DAI 枚举命名不同；寄存器宏取自 codec 头版本不同 |
| 5 | `bool (*)(struct snd_soc_codec *)` 与 `bool (*)(struct snd_soc_codec *, bool)` 不匹配 | **1** | 同一个 component 迁移的连带（`snd_soc_dapm_*` 回调签名变了） |

> 也就是说：**不是"搬文件就完"**，但也**不是从零写**。85 个错误里 64 个（第 1、3、4 类）
> 是机械替换，真正需要动脑的是第 2 类 component 迁移（15 处 + 连带）。

## 3. 已经做的（机械阶段，脚本化）

`bash tools/audio-rt5659-setup.sh <内核树>`（幂等）会做：

1. 从三星 3.18 包取出并放进 4.9 树：
   - `sound/soc/msm/msm8952_rt5659.c` → `techpack/audio/asoc/msm8952_rt5659.c`
   - `sound/soc/msm/msm-audio-pinctrl.h` → `techpack/audio/asoc/`
   - `sound/soc/codecs/msm8x16-wcd.h` → `techpack/audio/asoc/codecs/`
2. **include 布局适配**（已实测，改完错误从"头文件找不到"变成上面那 85 个真实错误）：
   | 三星 3.18 写法 | 4.9 techpack 写法 |
   |---|---|
   | `#include <sound/q6afe-v2.h>` | `#include <dsp/q6afe-v2.h>` |
   | `#include <sound/q6core.h>` | `#include <dsp/q6core.h>` |
   | `#include "qdsp6v2/msm-pcm-routing-v2.h"` | `#include "msm-pcm-routing-v2.h"` |
   | `#include "../codecs/rt5659.h"` | `#include "codecs/rt5659.h"` |
   | `#include "../codecs/msm8x16-wcd.h"` | `#include "codecs/msm8x16-wcd.h"` |
   （`sound/q6core.h`→`dsp/` 的替换也要在 `msm8x16-wcd.h` 里做一遍）
3. 让 **RT5659 codec 驱动**能被编进来：`SND_SOC_RT5659` 在 4.9 里是**无提示的 tristate**
   （只被 `SND_SOC_ALL_CODECS` select），所以要加一个自己的可见开关去 select 它：
   ```kconfig
   config SND_SOC_C7_RT5659
       bool "Realtek RT5659 codec for Galaxy C7"
       depends on I2C
       select SND_SOC_RT5659
   ```
   （和 `IIO_TRIGGERED_BUFFER` 那次同一个坑：无提示符号只能被 select）
4. **暂不**把机器驱动挂进 Kbuild（它现在还编不过）。脚本会在
   `techpack/audio/config/sdm450auto.conf` 里预留 `CONFIG_SND_SOC_RT5659_C7`（默认不打开），
   并在 `techpack/audio/asoc/Kbuild` 里写好条件行，等你把第 2 节的错误清完，打开它即可。

## 4. 下一步（照这个顺序做，每步都能单独验证）

1. **清第 1 类（be_id，49 处）**：以 `techpack/audio/asoc/msm8952-dai-links.c` 为模板
   （同平台、4.9 原生），把 BE dai link 改成 4.9 写法。
2. **补第 3 类字段（15 处）**：mach_data 加 `rt5659_ext_clk` / `codec_irq_gpio` / `codec` /
   `codec_ear_bias`（或改用它已有字段）。
3. **第 4 类枚举/宏（5 处）**：对照 4.9 的 `msm-pcm-routing-v2.h` 与
   `sound/soc/codecs/rt5659.h` 改名/改值。
4. **第 2 类 component 迁移（15 处 + 连带）**：把 `widget->codec` / `codec->dapm` 改成
   component 版本；回调签名按 4.9 调整。**这一步建议对着 4.9 的
   `msm8952-dai-links.c` + mainline 的 `sound/soc/codecs/rt5659.c` 一起改。**
5. ~~DTS 加 `sound` 节点 + `rt5659@1b`~~ ✅ **已完成**（补丁 0015）：
   `msm8953-c7ltechn-audio.dtsi` 里覆盖了 `&int_codec`（compatible 换成
   `qcom,msm8952-rt5659-audio-codec`）、加了 `rt5659@1b`，还**补出了 4.9 缺失的
   `i2c_6` 控制器**（C7 的 codec 挂在 BLSP2 QUP2 上）。DTB 实测已含这三样。
   剩下：启用 `CONFIG_SND_SOC_RT5659_C7` 编 `Image.gz-dtb` 并重打卡刷包。
6. ROM 侧**不用再动**：`mixer_paths.xml` / `audio_platform_info.xml` / `Tfa9897.cnt`
   已经由 `port/30-assemble-system.sh` 注入；DTS 引脚（`rt5659_contorl_active/suspend`、
   `rt5659_irq_active/suspend`）也早就转换好了。

## 5. 验证方式（没有真机之前能验到哪一步）

- **编译级**：`techpack/audio/asoc/msm8952_rt5659.o` + `sound/soc/codecs/rt5659.o` 0 error；
  `vmlinux` 里出现 `msm8952_rt5659_machine_probe`（或该文件里的 machine driver 符号）。
- **DTB 级**：反查编译出的 dtb 里有 `qcom,msm8952-rt5659-audio-codec` 与 `realtek,rt5659`。
- **真机级**（只能上机）：`tinymix`/`alsa_amixer` 看路由、播放测试音、耳机/外放/麦克风逐个验。

## 6. 相关文件

| 文件 | 作用 |
|---|---|
| `tools/audio-rt5659-setup.sh` | 机械阶段脚本（取文件 + include 适配 + codec 开关 + 安装 audio dtsi） |
| `kernel/patches/0015-dts-c7ltechn-add-rt5659-audio.patch` | DTS 补丁（sound 覆盖 + rt5659@1b + 补出 i2c_6） |
| `techpack/audio/asoc/msm8952-dai-links.c` | ★ 4.9 同平台外部 codec 机器驱动，改动模板 |
| `sound/soc/codecs/rt5659.c` | ★ 4.9 原生 RT5659 codec 驱动（component 版） |
| `techpack/audio/config/sdm450auto.conf` | msm8953 的 techpack 音频开关表 |
| `kernel/STATUS.md` / `docs/NEXT.md` | 总状态与剩余工作 |

---

## 7. 迁移结果（已完成）

**机器驱动 `techpack/audio/asoc/msm8952_rt5659.c`：`error 0 / warning 0`，模块与最终 `vmlinux` 都链接通过**（全量构建 `KBUILD_EXIT=0`，内核 `#12`，已打进最终卡刷包）
（`techpack/audio/` 整目录 `make` → `EXIT=0`，`machine_ext_dlkm.o` + `built-in.o` 都链出来了）。

### 7.1 落地方式

| 脚本 | 作用 |
|---|---|
| `tools/audio-rt5659-setup.sh` | 从三星 3.18 包取文件 + include 布局适配 + 装 audio dtsi + codec 开关 + 挂载点 |
| `tools/audio-rt5659-fixes.py` | 8 节幂等修补（见下），把机器驱动改到 4.9 |

### 7.2 八类差异与修法（全部实测）

| 节 | 差异 | 数量 | 修法 |
|---|---|---|---|
| 1 | `mach_data` 的 RT5659 扩展字段被 `#ifdef CONFIG_SND_SOC_MSM8X16_RT5659` 包着 | 15 错 | per-file `CFLAGS_msm8952_rt5659.o += -DCONFIG_SND_SOC_MSM8X16_RT5659`（不动头文件结构） |
| 2 | 4.9 删掉了 FE DAI 名 `CS_VOICE/VOICE2/VOLTE/VOWLAN` | 4 错 | 照抄 4.9 原生 `msm8952-dai-links.c:24-30` 的本地 enum（39~42） |
| 3 | `snd_soc_dai_link` 的 `be_id` 在 4.9 改名为 `id` | 52 处 | `.be_id/->be_id` → `.id/->id`（4.9 routing 读的正是 `rtd->dai_link->id`） |
| 4 | DAPM context 挪进 component | 9 处 | `codec->dapm` → `codec->component.dapm` |
| 5 | `snd_soc_dapm_widget` 删掉 `codec` 成员 | 8 处 | 取卡 `w->codec->component.card` → `w->dapm->card`；取 codec → `snd_soc_dapm_to_codec(w->dapm)` |
| 6 | 寄存器宏代差 | 1 处 | `RT5659_MICBIAS1` → `RT5659_MICBIAS_1`（值同 0x0093） |
| 7 | `wcd_mbhc_config.swap_gnd_mic` 多了 `bool active` 形参 | 1 处 | 函数补形参，实现不变 |
| 8 | **链接期**：4.9 没有 `msm8x16-wcd.c`，`msm8x16_wcd_mclk_enable()` 只有 extern 声明 | 4 处 | 改用本文件里的 `msm8952_rt5659_set_mclk()`（RT5659 走的本来就是外部 MCLK） |

### 7.3 顺手修掉的真 bug / 告警

- **重名**：`is_us_eu_switch_gpio_support()` 与 4.9 原生 `msm8952.c:434` 同名，两个模块都链进
  `built-in.o` → `multiple definition`（实测链接失败）。本文件只有一处调用 → 改 `static`。
- **缺花括号的逻辑 bug**：`if (atomic_dec_return(...) == 0)` 后面少一对花括号，导致紧随的
  `if (ret)` 实际落在 if 之外（`-Wmisleading-indentation` 指出的真实逻辑错误）→ 按缩进本意补上。
- **未使用函数**：`def_msm8952_wcd_mbhc_cal()` → `__maybe_unused`。
- **NULL 解引用风险**：`msm8952_rt5659_set_mclk()` 对 `pdata->rt5659_ext_clk` 没判空 → 加防御检查
  （DTS 没给 `ext-mclk` 时不再崩）。

### 7.4 Kbuild 两个坑（实测踩过，别再踩）

1. **对象必须挂 `machine_ext_dlkm-y`，不能往 `MACHINE_OBJS` 里加**：`asoc/Kbuild` 里
   `machine_dlkm-y := $(MACHINE_OBJS)` 是**立即展开**且在文件靠上位置，在文件末尾再
   `MACHINE_OBJS +=` 等于没加 —— 实测对象根本没被编出来。
2. **别用 `make techpack/audio/asoc/xxx.o` 单编**：单对象构建拿不到该目录的
   `EXTRA_CFLAGS/INCS`（`techpack/audio/include`），会报 `<dsp/q6afe-v2.h>` 找不到；
   要编就编整个 `techpack/audio/`（这才是真实路径）。

### 7.5 仍然存在的语义风险（真机才能验）

| 项 | 说明 |
|---|---|
| BE 号 `be_id`→`id` | 纯改名，风险低；但 4.9 的 `MSM_BACKEND_DAI_*` **枚举数值顺序与 3.18 不同**，全程用符号名所以与 4.9 routing 自洽。真机要逐个 BE 验（hostless/compress/BT SCO/FM/AUXPCM/MI2S） |
| FE DAI 名映射 | `CS_VOICE/VOICE2/VOLTE/VOWLAN` 在 4.9 里是**本地 enum（39~42）**，与 3.18 原值（23/30/28/42）不同，且在 4.9 里与 LSM7/LSM8/VOICE2_STUB/VOICEMMODE1 撞号 —— 这是 4.9 官方处理"废弃 FE DAI"的做法。**风险中**，真机验证 CS 语音 / VoLTE / VoWLAN / Voice2 通话 |
| `snd_soc_dapm_to_codec(w->dapm)` | 与 4.9 原生 `msm8952.c:178/225` 同款；这两个回调只被**从未注册**的 `msm8952_dapm_widgets[]` 引用（死代码），当前无运行期效果。若将来挂到 card dapm 上会非法，应改用 `pdata->codec` |
| `swap_gnd_mic(codec, active)` | 实现仍只翻 US/EU GPIO、忽略 `active`（与 4.9 原生及 3.18 一致）；仅 `!CONFIG_SAMSUNG_JACK` 路径编译。真机验 US/EU 耳机地麦交换 |
| `CONFIG_SAMSUNG_JACK` 分支 | **未移植**（+11 错：4.9 的 `struct snd_soc_jack` 无 `codec` 成员；`rt5659_imp_detect` 等三星私有 codec 钩子在 4.9 codec 里不存在）。该 4.9 树没有 `config SAMSUNG_JACK` 符号，当前不可达；若真机需要三星耳机检测要单独做 |
