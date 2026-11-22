# kernel/ — C7 的 Linux 4.9 内核（唯一必须"编"的一块）

> **为什么这里是例外？**
> 整个工程遵循"只移植不编译"，但**内核二进制没法跨设备移植**：
> 它必须包含 C7 的板级描述（面板、触摸、指纹、传感器中枢、充电、codec）和三星私有驱动，
> 而这些只存在于三星 3.18 源码里；同时 Android 15 又要求 ≥4.4/4.9 内核。
> 所以正确做法是：**把 C7 的板级支持"移植"到 4.9 内核树上，然后只编这一个内核**——
> LineageOS 本体一行源码都不用编。

---

## 1. 事实依据

| 结论 | 证据 |
|---|---|
| Android 12+ 需要 ≥ 4.9（实践下限 4.4） | LineageOS 官方 740 个设备里，**没有任何一台 3.x 内核设备**支持到 19/20/21/22；同 SoC 对照实验：小米 5 (MSM8996, 4.4) → 官方 LOS 22.2；一加 3 (MSM8996, 3.18) → 只到 18.1 |
| MSM8953 的 Android 15 事实标准是 **4.9.337** | zeelog mido lineage-22.2 = 4.9.337；`xiaomi-msm8953-devs` 的 lineage-20/21/22.x 全部 4.9.337 |
| C7 没有任何现成 4.9/4.14 内核 | `ai94iq/android_kernel_c7lte`（3.18，2018 停更）、`Galaxy-MSM8953/android_kernel_samsung_msm8953`（3.18.140）——全网没有 4.9 |
| 4.9 内核在 Android 15 上不需要 DMA-BUF heaps | LOS 22.2 的 mido/msm8953 设备树仍然 `TARGET_USES_ION := true`，LineageOS 用 `libion legacy_impl` 保留 ION |

**所以：C7 的 4.9 内核需要一次"板级移植 + 交叉编译"，这是本工程里唯一无法回避的编译。**

---

## 2. 已有素材（本仓库已放好）

`kernel/dts-3.18-source/` —— 从三星 3.18 内核源码树里抠出来的 C7 板级描述，作为移植的**源材料**：

| 文件 | 作用 |
|---|---|
| `msm8953-sec-c7lte_chn-r04.dts` | 国行 C7 的主 DTS（r04 = 最新硬件版本） |
| `msm8953-sec-c7lte_chn-pinctrl-r02.dtsi` | GPIO/引脚复用（触摸、指纹、NFC、codec…） |
| `msm8953-sec-c7lte_chn-battery-r00.dtsi` | 电池曲线 / 充电参数 |
| `msm8953-sec-common.dtsi` | 三星 msm8953 通用节点 |
| `Makefile` | 三星 DTS 的编译规则（看 dtb 是怎么拼出来的） |

主 DTS 里已经能读出关键硬件：

```dts
model = "Samsung Electronics. c7lte_chn";
compatible = "qcom,msm8953-mtp", "qcom,msm8953", "qcom,mtp";
#include ".../msm8953-sec-msm8953lte-chn-fingerprint-sensor_00.dtsi"
#include ".../S6E3FA3_AMS568HN31/dsi_panel_S6E3FA3_AMS568HN31_fhd_octa_cmd.dtsi"   ← 5.68" FHD AMOLED 面板
#include ".../S6E3FA3_AMS598KH01/dsi_panel_..._cmd.dtsi"                             ← 另一版本面板
#include ".../PBA_BOOTING_HD/dsi_panel_PBA_BOOTING_hd_video.dtsi"                    ← 开机 logo 面板
```

需要在 4.9 树里补齐的 Samsung 驱动（3.18 树里的路径）：

| 功能 | 3.18 源码路径 |
|---|---|
| AMOLED 面板 / mdss 三星扩展 | `drivers/video/msm/mdss/samsung/S6E3FA3_AMS568HN31/`、`.../samsung/`（mdss 里还有 `mdss_samsung_*` 一大票代码） |
| 触摸 | `drivers/input/touchscreen/sec_ts/`（另有 `imagis_30xxh/`、`stm/` 等变体，按 C7 实际用料取） |
| 指纹 | `drivers/fingerprint/`（`et5xx` / `vfs7xxx` 系列，走 SPI+Secure World） |
| 传感器中枢（Broadcom BHY） | `drivers/misc/bhy/`（`bhy_core.c`、`bhy_i2c.c` …） |
| 电池 / 充电 | `drivers/battery/sec_battery.c`、`sec_multi_charger.c`、`sec_step_charging.c`、`sec_board-msm.c` |
| 音频 codec / 功放 | `sound/soc/codecs/`（wcd-mbhc 系列）+ `TFA9897` 功放（i2c） |


### 2.1 C7 精确硬件（来自三星 3.18 的 C7 国行 defconfig，非猜测）

`kernel/c7-reference-defconfig-3.18.txt` 是三星 3.18 树里 **C7 国行真正的设备配置**
（`arch/arm/configs/msm8953_sec_msm895332lte_chn_defconfig`），它把 C7 到底用了谁的芯片说死了：

| 功能 | C7 实际用料 | 对应的 3.18 源码 |
|---|---|---|
| 面板 | **S6E3FA3_AMS598KH01**（r04；另有 AMS568HN31） | `drivers/video/msm/mdss/samsung/` + `CONFIG_FB_MSM_MDSS_SAMSUNG` |
| 触摸 | **MELFAS MMS449** + ABOV 触摸键 | `drivers/input/touchscreen/`（melfas 驱动） |
| 指纹 | **VFS7xxx**（SPI4，GPIO12-15） | `drivers/fingerprint/vfs7xxx.c` |
| 传感器中枢 | **Broadcom BHI** + SSC | `drivers/misc/bhy/` |
| 充电/电量计/MUIC/闪光灯 | **SM5705** 全家桶 | `drivers/battery/sec_*`、`drivers/mfd/` |
| 霍尔/翻盖 | HALL + CERTIFY_HALL | `drivers/sensors/` |
| NFC / eSE | 三星 NFC + PN548 + eSE P3 | `drivers/nfc/` |
| 音频 | QC codec + TFA9897 功放 | `sound/soc/codecs/` |

→ 4.9 的 defconfig 目标清单已经写成 **`kernel/c7lte-defconfig.fragment`**（含 Android 15 必需项 +
上面每一项的确切 Kconfig 符号）。

## 3. 移植路线（建议顺序）

```
① 建基线：克隆 4.9 树（推荐 zeelog/android_kernel_xiaomi_mido, branch lineage-22.2）
   —— 它已经带齐 Android 15 需要的 4.9 特性（backport、binder、ION、eBPF 相关 config），
      且 defconfig 就是 MSM8953 的，能直接编出 Image.gz-dtb。

② 加板级 DTS：把 kernel/dts-3.18-source/ 里的 c7lte DTS 转成 4.9 语法
   （3.18→4.9 的 qcom 绑定变化主要在：clock/regulator 的 phandle 名、
    pinctrl 的 state 写法、i2c/spi 的 `qcom,` 前缀、mdss 的 `qcom,mdss-dsi-*` 属性）。
   先做"能点亮屏幕"的最小集：面板 + 触摸 + 存储 + UART。

③ 搬驱动：按上表把 Samsung 驱动搬到 4.9（`mdss/samsung/`、`sec_ts`、`bhy`、`sec_battery`、
   `fingerprint`），补齐 Kconfig/Makefile，处理 3.18→4.9 的 API 变化
   （`->of_node`、`devm_*`、`drm_panel` 接口、`struct file_operations` 等）。

④ defconfig：以 mido 4.9 defconfig 为底，打开三星驱动与 C7 需要的 config
   （BHY、SEC_TS、SEC_BATTERY、fingerprint、TFA989x、S6E3FA3 面板…），
   并把 Android 15 需要的项确认打开：CONFIG_ANDROID_BINDERFS / CONFIG_BPF_SYSCALL /
   CONFIG_BPF_JIT / CONFIG_CGROUP_BPF / CONFIG_MEMFD_CREATE / CONFIG_ANDROID_BINDER_IPC。

⑤ 编译（本地或 GitHub Actions，见 build-c7lte-kernel.yml）→ 产出 Image.gz-dtb + *.ko。

⑥ 回灌到移植包：
     mkdir -p work/c7-kernel
     cp Image.gz-dtb work/c7-kernel/kernel
     cp -r <modules>/. work/c7-kernel/modules/
     bash port/40-make-bootimg.sh && bash port/50-make-zip.sh
   新包的文件名会自动变成 ...-kernel4.9.337.zip，不再是 EXPERIMENTAL。
```

## 4. 现实预期

- 这是**几周到几个月量级**的活（面板 + 触摸能点亮最快，RIL/相机/指纹最慢，参考同平台经验：
  bring-up 1~2 周，逐项外设 2~4 周，daily 级稳定 1~2 个月）。
- 里程碑建议：`M1 能亮屏进 recovery` → `M2 能过 init 进 bootanimation` → `M3 进桌面`
  → `M4 WiFi/音频` → `M5 RIL` → `M6 相机/指纹/传感器`。
- **不要一次把 3.18 的所有三星驱动全搬过去**，先做最小可用集，逐个加外设。

## 5. CI（GitHub Actions）

`.github/workflows/build-c7lte-kernel.yml` 是一个可以直接用的骨架：
在标准 `ubuntu-latest` runner 上（4 核 / 16 GB / 14 GB 磁盘）拉 4.9 树 + 打补丁 + 编内核，
产出 `Image.gz-dtb` 和 `modules` artifact。磁盘紧张，工作流里已经带了清理步骤。

用法：把本仓库推到 GitHub（或在你自己仓库里放 `kernel/` 目录），
然后 **Actions → build-c7lte-kernel → Run workflow**，填分支/defconfig 即可。
产物下载后按上面第 ⑥ 步回灌。

## 6. 已验证的第一步：C7 板级骨架 + 可编译的 DTB（本工程实测）

本工程已经把"落地点"做出来并**在真机上编过 DTB**：

| 产物 | 位置 |
|---|---|
| C7 板级 DTS 骨架 | `kernel/patches/0001-arm64-dts-qcom-add-msm8953-c7ltechn-board-scaffold.patch` |
| 应用方式 | CI 里 `git am kernel/patches/*.patch`（已实测 `git apply --check` 与 `git am` 均通过） |

实测记录（4.9.337 树 = zeelog/android_kernel_xiaomi_mido lineage-22.2）：

```bash
# 宿主机依赖（Ubuntu 24.04 实测）
apt-get install -y gcc-aarch64-linux-gnu gcc-arm-linux-gnueabi flex bison bc

cd <kernel-4.9>
make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     CROSS_COMPILE_ARM32=arm-linux-gnueabi- mido_defconfig
make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     CROSS_COMPILE_ARM32=arm-linux-gnueabi- qcom/msm8953-c7ltechn.dtb
```

结果：`DTC arch/arm64/boot/dts/qcom/msm8953-c7ltechn.dtb`，**234940 字节**；
反编译校验：

```
model          = "Samsung Galaxy C7 (SM-C7000)"
compatible     = "samsung,c7ltechn", "qcom,msm8953-mtp", "qcom,msm8953", "qcom,mtp"
qcom,msm-id    = <0x125 0x0>     # 293 = MSM8953
qcom,board-id  = <0x8 0x4>       # ★ C7 的真实 board-id（mido 是 <8 0>）
节点数          = 1124
```

> **这一步证明**：4.9 树的编译链、DTS 语法、C7 的 board-id 都对得上，
> 后面往里填外设时不会再被工具链问题干扰。
> **但它还不是一台能用的 C7 内核**：面板/触摸/指纹/SM5705/BHI 都还没接（见文件内 TODO）。


### 6.1 已验证的第二步：C7 引脚配置（143 → 60 个 pin state 落地）

三星 3.18 的 `msm8953-sec-c7lte_chn-pinctrl-r02.dtsi`（33 KB）是 gcdb 生成的，
结构是"外层包装 + 内层真正的 pin state"；4.9 只需要内层、直接挂到 `&tlmm`。
本工程写了 `tools/dts-pinctrl-318to49.py` 做这个机械转换，并把"与 4.9 基线 DTS 撞 label"
的节点自动滤掉：

```
3.18 原始 pin state          143 个
与 4.9 基线(SOC+MTP)重名      -83 个（i2c_3/uart_console/mdss_*/cci*/sdc_* 等标准组，用 4.9 自带的）
保留的 C7 专属 pin state       60 个
```

保留下来的正是 C7 真正独有的东西（都在 DTB 里验证过）：

| 类别 | label |
|---|---|
| 触摸 | `tsp_int_active/suspend`（gpio59） |
| 触摸键 | `touchkey_i2c_*`、`touchkey_int_*` |
| 电源 SM5705 | `sm5705_i2c_*`、`sm5705_interrupt_*`、`sm5705_rst_*`、`sm5705_rgb_*` |
| 指纹 SPI | `spi_4_*`、`spi1_cs0_*` |
| NFC | `nfc_enable_*`、`nfc_pwr_req_*` |
| 传感器/其它 | `prox_sensor_*`、`hall_int_*`、`sensor_ldo_en_*`、`earjack_*`、`flash_led_*` |
| 音频 | `quin_tlmm_*`、`rt5659_*` |
| 扩展 i2c | `i2c_6_*`、`i2c_7_*` |

结果：`msm8953-c7ltechn.dtb` **244264 字节，干净编译**，反编译确认节点都在。
补丁：`kernel/patches/0002-arm64-dts-qcom-c7ltechn-add-pinctrl.patch`（两个补丁依次 `git am` 实测通过）。

> 这两个补丁合起来，等于"**C7 的板级骨架 + 全套引脚定义**"已经进了 4.9 树，
> 后面接触摸/PMIC/指纹/NFC/音频驱动时，pinctrl 引用（`pinctrl-0 = <&tsp_int_active>`）
> 已经可以直接用了。


### 6.2 已验证的第三步：C7 触摸 / 触摸键节点（并核对了驱动可得性）

补丁 `0003-arm64-dts-qcom-c7ltechn-add-touch.patch` 把 C7 的输入设备从 3.18 原样搬了过来：

| 设备 | 总线（都是**软件 I2C**） | 节点 |
|---|---|---|
| MELFAS MMS449 触摸 | `i2c@11`：sda=gpio39 / scl=gpio38 | `mms_ts@48`，irq=gpio59，1080×1920，fw `tsp_melfas/mms449_c7.fw` |
| ABOV MC96FT16xx 触摸键 | `i2c@23`：sda=gpio16 / scl=gpio17 | `mc96ft16xx@20`，irq=gpio60，fw `abov/abov_tk_1604_c7.fw` |

两条软 I2C 的引脚正好落在上一补丁的 `fg_i2c_*` / `touchkey_i2c_*` pin state 上，pinctrl 引用能直接对上。

**驱动可得性（逐个核对过源码树，结论差很多）：**

| 设备 | 驱动在公开三星 3.18 树里吗 | 出路 |
|---|---|---|
| ABOV 触摸键 | ✅ `drivers/input/keyboard/abov_touchkey_16xx.c`，`compatible = "abov,mc96ft16xx"` 完全对得上 | 直接移植到 4.9 即可 |
| MELFAS MMS449 触摸 | ❌ **不在**。树里只有另一颗 MELFAS 触摸键 `melfas_mip4/`（MHS204）；原厂也没编成模块（stock `/system/lib/modules` 里只有测试模块） | 说明它被编进了原厂内核但源码没随开源包放出 → 需要从别的三星机型内核树里取 `mms_ts` 驱动（同为 i2c input 驱动）再移植 |

> 这个"驱动缺一颗"的结论是实测出来的（翻了三星 3.18 树文件列表 + `tunusahinn` 原厂 dump 的
> `/system/lib/modules`），已写进补丁说明，避免后面有人以为 DTS 摆好就能用。

结果：`msm8953-c7ltechn.dtb` **245618 字节，干净编译**，反编译确认四个节点与关键属性都在。


### 6.3 已验证的第四步：**第一个 C7 驱动移植并编译通过**（ABOV 触摸键）

`kernel/patches/0004-input-keyboard-port-abov-touchkey.patch` 把三星 3.18 的
`abov_touchkey_16xx.c`（1912 行）搬进了 4.9 树，并**实测编译 + 目录级链接通过**：

```
CC  drivers/input/keyboard/abov_touchkey_16xx.o   (249776 bytes)
CC  drivers/input/keyboard/abov_touchkey_sec.o    (124912 bytes)
LD  drivers/input/keyboard/built-in.o             链接通过
```

**三星私有依赖的处理（都是编不过才补的，不是照抄）**

| 依赖 | 处理 | 原因 |
|---|---|---|
| `sec_class` / `sec_device_create` | 新增 `abov_touchkey_sec.c` 实现（subsys_initcall 建 class + `device_create`） | 驱动后面会 `sysfs_create_group(&sec_touchkey->kobj, …)`，**必须返回有效指针**，不能返回 NULL/错误 |
| `SECLOG`、`input_err/info/dbg`、`KEY_RECENT` | 新增 `include/linux/sec_class.h` shim，按调用语义重实现 | 三星塞在自家 `input.h` / `input-event-codes.h` 里，AOSP 没有 |
| `module_init_async` | `include/linux/async_initcall.h` → `module_init` | 行为等价（同步注册） |
| `CONFIG_INPUT_BOOSTER`、`CONFIG_TOUCHSCREEN_DUMP_MODE` | **不用管** | 驱动里本来就 `#ifdef` 包着，不开这两个 config 自动不参与编译 |
| `reverse_key < 0`（bool 比 0） | 按文件 `-Wno-error=bool-compare` | 4.9 默认 `-Werror` |

> 这几个 shim 是**可复用的**：后面移植 SM5705 / BHI / NFC / 相机等三星驱动时，
> `sec_class`、`SECLOG`、`input_*` 这些坑都已经填好，不会再卡一遍。

**配套改动**

- 新增 `arch/arm64/configs/c7ltechn_defconfig` = `mido_defconfig` + C7 已落地驱动（目前就 ABOV 一项）；
  CI 工作流的 `defconfig` 默认值已改成它。
- DTS 侧（补丁 0003）的 `compatible = "abov,mc96ft16xx"` 与驱动 `of_device_id` **逐字一致**，
  总线 `i2c@23`、irq gpio60、`tkey_en` gpio132、固件名都已对上。

**四个补丁依次 `git am` 实测通过**（已在干净 4.9 树上验证）。


### 6.4 已验证的第五步：SM5705 电源节点（充电/MUIC/闪光灯）

补丁 `0005-arm64-dts-qcom-c7ltechn-add-sm5705.patch`：把 C7 的 SM5705 电源部分搬进 4.9 骨架。

```
i2c@8 (SW I2C, sda=gpio98 scl=gpio99)
  ├── muic-sm5705@25   MUIC  USB/OTG/充电器识别   IRQ gpio63
  ├── sm5705@49        SM5705 充电器              IRQ gpio61
  └── sm5705_fled      闪光灯/手电筒（gpio36/20/34/8 双路）
根节点 muic { }        配件识别电阻表（+OTG/-MHL/+TA/+USB/…）
```

引脚引用全部落在补丁 0002 转换过来的 pin state 上
（`sm5705_i2c_*` / `sm5705_interrupt_*` / `sm5705_rst_*` / `sm5705_rgb_*` / `charger_int_active`）。

验证：`msm8953-c7ltechn.dtb` **247533 字节，干净编译**；反编译确认
`sm5705@49`(reg 0x49, irq gpio61) / `muic-sm5705@25`(reg 0x25, irq gpio63) /
`sm5705_fled` / `muic` / `i2c@8` 都在，pinctrl 引用已解析。

> 顺带发现三星在公开树里还带了一份 msm8953 通用的 `msm8953-sm5705.dtsi`（on7xelte 等在用），
> 与 C7 的版本高度相似，可以作为交叉参考（本补丁用的是 C7 自己的真实取值）。

### 6.5 驱动可得性全清单

`kernel/driver-availability.md` 把 C7 的每个外设逐个核对了公开三星 3.18 树，结论：

- ✅ **在手上**：面板（含三星 mdss）、触摸键、指纹 VFS7xxx、BHI、SM5705 全套、NFC(pn547/ese_p3)、
  WCD codec、sec_thermistor
- ⚠️ **需加工**：TFA9897 功放（树里只有近亲 tfa9872）、振动
- ❌ **公开树里没有，必须外部取得**：**MELFAS MMS449 触摸驱动**、**相机 8 颗 sensor 驱动**
  （这两项是三星开源包的保留项，已验证：`mms114.c` 不覆盖 `melfas,mms_ts`；
  `camera_v2/sensor/` 里只有框架没有具体 sensor）


### 6.6 已验证的第六步：温度检测链路（thermistor + mux_sel）

补丁 `0006-hwmon-misc-port-sec-thermistor-and-mux-sel.patch`：

| 文件 | 说明 |
|---|---|
| `drivers/hwmon/sec_thermistor.c`（441 行） | 多路热敏电阻（AP/电池/充电器温度） |
| `drivers/misc/sec_mux_sel.c`（474 行） | PMIC MPP 在多个 ADC 通道间切换 |
| **`include/linux/wakelock.h`** | ★ **通用 shim**：4.9 删掉了 Android wakelock，用 `wakeup_source` 做薄封装 |
| `msm8953-c7ltechn-thermistor.dtsi` | C7 的真实标定表（adc_array / temp_array 各 91 点，adc_channel=19） |

```
CC  drivers/hwmon/sec_thermistor.o   (162968 bytes)
CC  drivers/misc/sec_mux_sel.o       (159712 bytes)     ← 首次编译即通过
DTC arch/arm64/boot/dts/qcom/msm8953-c7ltechn.dtb  (248466 bytes)
```

> **wakelock shim 是一笔划算的投资**：它是 NFC(pn547)、指纹(vfs7xxx)、eSE(ese_p3) 的公共拦路虎
> （`driver-dep-scan.sh` 显示这三个都缺 `linux/wakelock.h`），现在一次填平。
> 新工具 `tools/driver-dep-scan.sh` 可以按"缺几个头文件"给候选驱动排优先级。


### 6.7 已验证的第七步：指纹链路（VFS7xxx / SPI4）

补丁 `0007-fingerprint-port-vfs7xxx.patch`：

```
CC  drivers/fingerprint/vfs7xxx.o            (1825 行驱动本体)
CC  drivers/fingerprint/fingerprint_sysfs.o
LD  drivers/fingerprint/built-in.o
DTC msm8953-c7ltechn.dtb                     (250994 bytes)
```

两个只有真编才发现的坑：

1. **4.9 的 msm8953.dtsi 里根本没有 `spi_4`**（只有 `spi_3`/`spi_6`）——三星是在自己的 3.18 指纹
   dtsi 里补的整颗 BLSP1 QUP4。本补丁按 4.9 `spi_3` 的写法把它补出来
   （reg `0x78b8000/0x7884000`、irq 98/238、bam pipe 10/11、qup4 spi 时钟宏都确认存在）。
2. 指纹的引脚状态（`vfsspi_drdypin_*`/`ldopin`/`sleeppin`/`vendorPin`）在 3.18 里写在**指纹 dtsi**
   而不是 pinctrl dtsi 里 → 同样用 `tools/dts-pinctrl-318to49.py` 转换后并入 `&tlmm`。

DTS 用 C7 原值并在 DTB 里复核：`vfsspi-sleepPin=gpio140`、`drdyPin=gpio25`、`ldoPin=gpio89`、
`vendorPin=gpio130`、`spi-max-frequency=19200000`、别名 `spi4 = &spi_4`。

> 备查：三星原文件在同一个 SPI 总线上还挂了 `etspi-spi@1`（compatible `etspi,et320`），
> 那是给用 ET320 指纹的其它批次准备的；C7 的 defconfig 选的是 VFS7XXX，所以只保留了 vfsspi。


### 6.8 已验证的第八步：NFC（pn547）+ 修掉一个会坑死显示的真 bug

**先修 bug（补丁 0008）**：`dts-pinctrl-318to49.py` 原来按 label 名字判重——只要 4.9 基线里有同名
label 就丢掉 C7 的定义。但**同名不等于同引脚**！实测揪出 10 个引脚号不同的：

| label | C7 | 4.9 基线 | 影响 |
|---|---|---|---|
| **`mdss_dsi_active/suspend`** | gpio **50,94** | gpio 59,61 | **显示！丢了面板根本点不亮** |
| `nfc_int_active/suspend` | gpio 21 | gpio 17 | NFC 中断 |
| `cam_sensor_rear_*` | gpio 40 | gpio 39,40 | 相机 |
| `cam_sensor_front_*` | gpio 129 | gpio 131,132 | 相机 |
| `gpio_key_*` | gpio 85,86 | gpio 85,86,87 | 按键 |

工具已升级：`--baseline-dts`（连引脚号一起比对）+ `--rename-prefix`（不同的加前缀保留，
如 `c7_mdss_dsi_active`），转换结果 **60 → 70 个 pin state**。

**再上 NFC（补丁 0009）**：

```
CC  drivers/nfc/pn547.o                    (1781 行，PN547/PN548)
LD  drivers/nfc/built-in.o
DTC msm8953-c7ltechn.dtb                   (252990 bytes)
```

移植时改的 3 处接口差异（都写在补丁说明里）：
1. `<mach/msm_xo.h>` → `<linux/msm_xo.h>`（新增 shim，TCXO 投票退化为空实现）
2. 删掉 `<asm/siginfo.h>`（4.9 已移除；驱动实际没用到）
3. **不编译 `nfc_logger.c`**：三星那个头是"同名宏 + 同名函数"的历史写法，4.9 直接编会炸；
   头文件自带 stub 分支，`NFC_LOG_*` 映射到 `pr_err/pr_info` 就够用

DTS 用 C7 原值并在 DTB 复核：`pn547@2B` on `i2c_3`，irq gpio21 / ven 67 / firm 68 / pwr_req 70 / pvdd 69，
pinctrl 引用 `c7_nfc_int_*`（因为 C7 的 NFC 中断是 gpio21，基线是 gpio17）。


### 6.9 面板（最难的一块）：规模已量清，源料已就位

面板是"能不能用"的分水岭，也是 mdss 里最硬的一块。本轮把它的规模**量出来**了：

| 事实 | 数据 |
|---|---|
| 4.9 的显示驱动位置 | `drivers/video/fbdev/msm/`（4.9 从 `video/msm/mdss/` 挪走了） |
| 两边是否同源 | 是，都是 CAF mdss **fbdev**（mido defconfig 就是 `CONFIG_FB_MSM_MDSS=y`） |
| 差异规模 | `mdss_dsi_panel.c` 三星多 477 行 / `mdss_dsi.c` 多 581 行 / `mdss_fb.c` 多 329 行 —— **可移植的增量，不是重写** |
| 三星改动点 | `mdss_dsi_panel.c` 里 **22 处** `samsung_*` 挂钩（4.9 版 = 0 处），清单见方案文档 |
| 面板驱动 | C7 面板 981 行 + smart_dimming + mdnie + 面板 dtsi（时序/初始化序列） |
| 框架 | 顶层 `samsung/` 11 个 .c + 13 个头/Kconfig/Makefile |

源料已归档到 `kernel/panel-3.18-source/`（C7 主面板 AMS598KH01、另一版本 AMS568HN31、整套框架），
完整步骤/风险/备选方案见 **`kernel/panel-port-plan.md`**。

> 顺带说明 DTS 侧的前置条件已经就绪：C7 的显示引脚是 `mdss_dsi` gpio(50,94)，与 4.9 基线(59,61)不同，
> 已在补丁 0008 里作为 `c7_mdss_dsi_active/suspend` 找回 —— 这正是"同名不同脚"那个 bug 的最大受害者。

### 6.10 面板移植重大进展（第 15–18 轮）

| 步骤 | 结果 |
|---|---|
| 换用 bak-2 分支的同代面板框架 | ✅ 框架 4/4 对象 + C7 面板驱动 398KB + built-in.o 链接通过 |
| 4.9 显示核心与三星栈共存编译 | ✅ `mdcc_fb.o` / `mdss_dsi_panel.o` 均通过 |
| 核心侧缺的 2 个三星函数移植 | ✅ `mdss_samsung_parse_dcs_cmds` / `mdss_samsung_panel_cmd_read`（符号 T） |
| 核心挂钩第一批（reset 时序） | ✅ 上/下电复位延时 + `samsung_get_vdd`，并导出 `mdss_dsi_panel_cmds_send` |
| 剩余挂钩 | ⏳ `_on` / `_off` / 框架入口（清单见 `kernel/panel-hooks.md`） |

> 关键经验：面板框架与面板驱动必须**同代**。公开树里 `lineage-16.0` 的框架比 C7 面板驱动旧，
> 表现为"缺 21 个结构体成员 + 一堆不存在的 API"；换到 `bak-2` 后一次对齐。

顺带说明两个坑（都已踩过）：
1. `CC=gcc` 不要乱设（会让 `scripts/mod/empty.o` 因为 `-mlittle-endian` 报错）——
   DTS 预处理也用 `$(CC)`，直接给交叉编译器即可；
2. `CROSS_COMPILE_ARM32` 不能为空（`arch/arm64/Makefile` 会直接 error），
   需要装 `gcc-arm-linux-gnueabi` 或至少给个非空值。
