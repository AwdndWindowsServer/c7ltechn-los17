# 内核移植状态总表（C7 → Linux 4.9）

> 这是内核侧的唯一总入口。细节分散在各专项文档里，本页给出**当前状态、证据、下一步**。
> 更新时间：触摸落地（补丁 0011）之后 —— 11 个补丁的完整序列已在纯净 mido 树上实测依次干净应用。

---

## 1. 一句话状态

**4.9 内核已经编完并装进正式卡刷包了**：`Image.gz-dtb`（内核 `4.9.337-perf #12`）+ 安卓 15 ramdisk
+ C7 fstab，**最终产物**见 `out/lineage-22.2-c7ltechn-port-20260926-kernel4.9.337.zip`
（`20260925` 那份是"加音频之前"的，留作对照）。

在 4.9.337 树上**编译验证通过**的有：DTS 板级描述、7 类外设驱动（触摸键/温度/指纹/NFC/触摸 MIP4/**SM5705 充电+电量计+MFD**/USB 通知层）、
整套三星显示栈（框架 + C7 面板驱动 + 核心挂钩）。**注意：包内那份 boot.img 还是加电池栈之前编的**，
要带上电池栈得增量重编一次（`kernel/STATUS.md` §3 第 2 步 + `port/45-install-kernel.sh`）。
剩余为：直连传感器（TMD3700/YAS539）、MUIC/闪光灯驱动、三星耳机检测（`CONFIG_SAMSUNG_JACK` 分支），以及公开树里没有源码的 8 颗相机 sensor 驱动
（结论见 `kernel/driver-availability.md`）。

---

## 2. 已完成并验证的部分

| 模块 | 内容 | 验证方式 |
|---|---|---|
| **板级骨架** | `msm8953-c7ltechn.dts`（board-id `<8 4>`、msm-id 293） | DTB 编译 + 反编译核对 |
| **引脚配置** | 70 个 C7 专属 pin state（含从基线"同名不同脚"里找回的 10 组） | DTB 编译 |
| **触摸 / 触摸键** | `mms_ts@48`（软 I2C gpio39/38，irq 59）、`mc96ft16xx@20`（软 I2C gpio16/17） | DTB 编译 |
| **SM5705 电源** | MUIC + 充电器 + 闪光灯 + 配件表（`i2c@8`，软 I2C gpio98/99） | DTB 编译 |
| **热敏电阻** | `sec_thermistor`（C7 真实标定表 91 点，adc_channel 19） | DTB 编译 |
| **指纹** | `vfsspi-spi@0`（SPI4 = 补出的 BLSP1 QUP4，gpio140/25/89/130） | DTB 编译 |
| **NFC** | `pn547@2B` on `i2c_3`（irq 21 / ven 67 / firm 68 / pwr_req 70 / pvdd 69） | DTB 编译 |
| **驱动：ABOV 触摸键** | `abov_touchkey_16xx.c`（1912 行）+ sec_class/async_initcall/SECLOG shim | 编译链接通过 |
| **驱动：温度链路** | `sec_thermistor.c` + `sec_mux_sel.c` + **wakelock shim** | 编译通过（首次即过） |
| **驱动：指纹** | `vfs7xxx.c` + `fingerprint_sysfs.c` + 补出的 SPI4 总线节点 | 编译链接通过 |
| **驱动：NFC** | `pn547.c`（1781 行）+ `msm_xo.h` shim | 编译链接通过 |
| **驱动：触摸（MIP4）** | 主线 4.14 `melfas_mip4.c`（Rev 5.4，1631 行）= 补丁 0011；DTS 双 compatible + `ce-gpios` | 编译链接通过；`Image` 内含 MIP4 字符串，`vmlinux` 有 26 个 mip4 符号 |
| **电源：SM5705 电池栈** | `sec_battery.c`(9444) + `sm5705_charger.c`(2097) + `sm5705_charger_oper.c` + `sm5705_fuelgauge.c`(2781) + `sec_step_charging.c` + MFD `sm5705.c`/`sm5705-irq.c`；22 个电池头 + `drivers/usb/notify` | **7 个 .o 全部 0 error**；与旧 `vmlinux` 对照仅剩 `memset` 未定义（编译器内建）；DTB 内含 `sm5705-fuelgauge,i2c` |
| **电源：power_supply 兼容层** | 3.18 老式 `psy->set_property`/`container_of` 模型 → 4.9 的 desc+cfg 模型；补 6 属性 / 29 类型 / 2 健康值 + **3 张 sysfs 文本表防越界** | `tools/battery-fixes.py`（幂等，9 节，重跑零改动实测） |
| **电源：电量计 DTS** | 补丁 0012：`sm5705-fuelgauge@71`（补丁 0005 漏了这个节点） | 已在编译进 DTB 的节点里验证 |
| **音频：机器驱动** | `techpack/audio/asoc/msm8952_rt5659.c`（3809 行，`tools/audio-rt5659-setup.sh` + `audio-rt5659-fixes.py` 八节幂等修补）+ 它依赖的 `msm-audio-pinctrl.c`；RT5659 codec 驱动 `sound/soc/codecs/rt5659.c` | **编译 0 error / 0 warning，模块与 `vmlinux` 链接通过**；`vmlinux` 里有 `msm8952_rt5659_disable_mclk`/`rt5659_sysclk`/`rt5659_dapm_widgets`/`rt5659_i2c_probe`/`msm_gpioset_initialize` |
| **音频：DTS 侧** | 补丁 0015：`&int_codec` 覆盖成 `qcom,msm8952-rt5659-audio-codec` + `rt5659@1b`（i2c 0x1b）+ **补出 4.9 缺失的 `i2c_6` 控制器** | DTB 实测含 `qcom,msm8952-rt5659-audio-codec`/`realtek,rt5659`/`i2c@7af6000`；机器驱动内部还在迁移 |
| **传感器中枢：BHI** | `drivers/misc/bhy/`（`bhy_core.c` 212 KB + `bhy_i2c.c` + `bstclass.c`）+ 它依赖的 `drivers/sensors/sensors_core.c`（369 行，`/sys/class/sensors`）；补丁 0014 给 DTS 加 `bhy@28`（i2c_5，中断 gpio42，LDO gpio66）+ `i2c_5_active/sleep` | **编译 0 error**（`tools/bhy-fixes.py` 把 3.18 的 IIO ring API 改成 4.9 的 `iio_triggered_buffer_setup`，并让 Kconfig select `IIO_TRIGGERED_BUFFER`）；与 ROM 里注入的三星 HAL + `bhy_firmware` 配套 |
| **NFC shim 适配** | 补丁 0013：`poweroff_charging` 改 `__weak`，让电池栈里的真定义生效（否则 `drivers/built-in.o` 重复定义） | 链接实测（先报 multiple definition，改后通过） |
| **显示：三星框架** | bak-2 分支的框架 4/4 对象（同代，与面板驱动匹配） | 编译通过 |
| **显示：C7 面板驱动** | `ss_dsi_panel_S6E3FA3_AMS598KH01.o` 398KB + smart_dimming 157KB | 编译链接通过 |
| **显示：核心侧函数** | `mdss_samsung_parse_dcs_cmds` / `mdss_samsung_panel_cmd_read` | 编译通过（符号 T） |
| **显示：核心挂钩** | reset 上/下电延时、`samsung_get_vdd`、`_on`/`_off` 的 `on/off_pre/post` | 编译通过，框架引用 4 处 |
| **全量构建 + 打包** | `Image.gz-dtb` 12,689,460 B（`#10 SMP PREEMPT`，含电池栈/BHI/触摸/显示）+ `diagchar.ko` | **`KBUILD_EXIT=0`**；`port/45-install-kernel.sh` 出的 zip 内 boot.img 14,395,392 B，kernel_size 与之一致 |
| **构建体系** | `c7ltechn_defconfig`、GitHub Actions 工作流、**15 个可 `git am` 的补丁** | 补丁序列在纯净 mido 树上依次应用实测 + 与构建树逐字节比对 |

### 关键 shim（可复用）

`sec_class` / `async_initcall` / `SECLOG` / `input_err,info,dbg` / `KEY_RECENT` /
**`wakelock`**（NFC/指纹/eSE 都要）/ **`msm_xo`**（TCXO 投票退化）。

---

## 3. 复现方式（全部脚本化）

```bash
# 0) 内核源码侧：拿到纯净 mido 4.9 树后，12 个补丁依次应用即得到"补丁态"树
git am kernel/patches/00*.patch          # 0001..0015，实测依次干净应用（0012/0014/0015 另做正反向检查）

# 1) 主流水线：出 ROM 包
sudo bash port/run-all.sh            # donor 解包 → system 组装 → boot → 卡刷包

# 2) 内核侧：把人工改动打进 4.9 树（幂等，可重复跑；与补丁 0001-0011 互补：
#    补丁管"可 diff 的源码改动"，脚本管"整目录搬运 + 生成式配置"）
bash tools/panel-framework-setup.sh  work/kernel-4.9   # 面板框架 + 10 类接口修补 + 核心挂钩
bash tools/touch-mip4-setup.sh       work/kernel-4.9   # 触摸驱动（等于补丁 0011，幂等）
python3 tools/panel-core-hooks.py    work/kernel-4.9   # 核心 2 函数 + reset/on/off 挂钩
bash tools/battery-sm5705-setup.sh   work/kernel-4.9   # SM5705 电池栈搬运 + 接线 + MFD（内部会调 battery-fixes.py）
bash tools/bhy-sensorhub-setup.sh    work/kernel-4.9   # BHI 传感器中枢搬运 + 接线 + DTS（补丁 0014 的脚本等价实现）
bash tools/audio-rt5659-setup.sh     work/kernel-4.9   # RT5659 机器驱动/codec 开关/audio DTS（补丁 0015）
python3 tools/audio-rt5659-fixes.py  work/kernel-4.9   # 机器驱动的 3.18→4.9 八节修补（幂等，独立重跑也 0 改动）
python3 tools/battery-fixes.py       work/kernel-4.9   # power_supply 3.18→4.9 兼容层（单独重跑也幂等）

# 3) 编好内核后，一键装进 ROM 包（换 boot.img + 重打卡刷包）
bash port/45-install-kernel.sh \
     work/kernel-4.9/out/arch/arm64/boot/Image.gz-dtb \
     work/kernel-4.9/out/modules-install/lib/modules

# 4) 编 DTB / 内核对象验证
cd work/kernel-4.9
make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     CROSS_COMPILE_ARM32=arm-linux-gnueabi- qcom/msm8953-c7ltechn.dtb
```

其他工具：`tools/kernel-port-headers.sh`（缺头文件自动补全）、`tools/driver-dep-scan.sh`（驱动移植代价评估）、
`tools/dts-pinctrl-318to49.py`（3.18→4.9 引脚转换）、`tools/panel-framework-fixes.py`（接口修补实现）。

---

## 4. 还没做的（按优先级）

| 优先级 | 项目 | 现成资料 |
|---|---|---|
| ★★★ | **相机 8 颗 sensor 驱动** | 公开树（含各 fork）只有框架，无 sensor 驱动；结论与检索证据见 `kernel/driver-availability.md` |
| ★★ | **音频（已测绘，进行中）** | ★ 实测 85 个错误（49 `be_id` / 15 component+DAPM / 15 mach_data 字段 / 5 枚举宏 / 1 回调签名），完整方案见 `kernel/audio-rt5659-port-plan.md`；机械阶段已脚本化（`tools/audio-rt5659-setup.sh`），**RT5659 codec 驱动已编进树（0 error）**。详见下方原条目：C7 用的是 **RT5659**（i2c 0x1b，`sound` 节点 compatible `qcom,msm8952-rt5659-audio-codec`），不是 donor 的 WCD9335。**codec 驱动 `sound/soc/codecs/rt5659.c` 4.9 树里就有**，缺的是三星机器驱动 `sound/soc/msm/msm8952_rt5659.c`（**3809 行**，公开树里有、本树没有），而 4.9 的 msm 音频已经搬到 vendor 拆分 `techpack/audio/asoc/`（接口与 3.18 完全不同）。DTS 侧引脚（`rt5659_contorl_active/suspend`、`rt5659_irq_active/suspend`）与 ROM 侧参数（`mixer_paths.xml`/`audio_platform_info.xml`/`Tfa9897.cnt`）都已就位 |
| ★ | 直连传感器驱动 | C7 还有两颗直连 i2c 传感器：`tmd3700@39`（光/距，三星驱动 `drivers/sensors/tmd37xx.c` 69 KB）与 `yas539@2e`（磁力，`yas_mag_kernel.c`+`yas_mag_drv-yas539.c`）。BHI 管的是 hub 后面的 accel/gyro；这两颗要单独搬 |
| ★ | 真机验证 | 需要真机 + TWRP（先按 `docs/04` 备份 EFS/modemst/persist） |
| ~~★★~~ | ~~BHI 传感器中枢~~ | **已完成**：驱动搬运 + DTS（补丁 0014）都就位；传感器能否真正工作还要真机看 HAL 与固件 |
| ~~★★~~ | ~~SM5705 充电 + 电量计~~ | **已完成**：搬运+兼容层+MFD 全部编译通过（见上表）；MUIC/闪光灯驱动仍未搬（不影响电池栈编译） |
| ~~★★★~~ | ~~MMS449 触摸驱动~~ | **已完成**（补丁 0011，主线 MIP4 Rev 5.4）；无公开三星源码这一点已固化在 `kernel/melfas-mip4-mainline/README.md` |

---

## 5. 专项文档索引

| 文档 | 内容 |
|---|---|
| `kernel/dts-3.18-source/` | C7 板级 DTS 源料（3.18，含面板/指纹/相机 sensor 声明） |
| `kernel/panel-3.18-source-bak2/` | **同代**面板框架 + C7 面板驱动源料（当前使用） |
| `kernel/panel-3.18-source/` | lineage-16.0 的旧框架（留作对比，勿用） |
| `kernel/audio-rt5659-port-plan.md` | **音频移植方案（实测工程量）**：4.9 techpack 架构、85 个错误分类与修法、落地顺序、验证方式 |
| `kernel/melfas-mip4-mainline/README.md` | 触摸方案：为什么用主线 MIP4、"三星树没有 MMS449 源码"的检索证据、4.14 vs master 的选型依据 |
| `kernel/patches/` | 11 个补丁 = 完整的可复现源码改动序列（`git am kernel/patches/00*.patch`） |
| `kernel/panel-port-plan.md` | 面板移植全过程：规模量化 → 版本不匹配诊断 → 换 bak-2 → 挂钩清单 |
| `kernel/panel-hooks.md` | 22 处挂钩的精确清单与完成进度 |
| `kernel/DTS-3.18-to-4.9.md` | DTS 写法逐项对照 |
| `kernel/driver-availability.md` | 每个外设驱动的可得性与移植难度 |
| `kernel/c7ltechn_defconfig.fragment` | 配置目标清单（含每项对应的 Kconfig 符号） |
| `kernel/README.md` | 内核侧总说明与各轮实测记录 |
| `../.github/workflows/build-c7lte-kernel.yml` | GitHub Actions 一键编内核 |
