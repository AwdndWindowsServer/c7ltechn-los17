# DTS 3.18 → 4.9 移植对照手册（c7ltechn）

> 目的：把三星 3.18 内核里 C7 的板级描述搬进 MSM8953 的 4.9 内核树。
> 两边语料都在本仓库里，可以边看边改：
>
> - **3.18 源**：`kernel/dts-3.18-source/`（从 `Galaxy-MSM8953/android_kernel_samsung_msm8953` @lineage-16.0 抠出）
> - **4.9 目标**：`kernel/mido-4.9-reference/`（从 `zeelog/android_kernel_xiaomi_mido` @lineage-22.2 抠出）
> - 4.9 树的完整版：`git clone --depth=1 -b lineage-22.2 https://github.com/zeelog/android_kernel_xiaomi_mido`

---

## 0. 两棵树的目录约定不同（先搞清楚这个）

| | 3.18 三星树 | 4.9 mido 树 |
|---|---|---|
| 板级目录 | `arch/arm64/boot/dts/samsung/msm8953/` | `arch/arm64/boot/dts/qcom/`（设备相关可放子目录，如 `qcom/mido/`） |
| 芯片公共 dtsi | `arch/arm64/boot/dts/qcom/msm8953*.dtsi` | 同左 |
| 设备主 DTS | `msm8953-sec-c7lte_chn-r04.dts` | `msm8953-mtp.dts` + `qcom/mido/*.dtsi` |
| 面板 | `drivers/video/msm/mdss/samsung/<PANEL>/dsi_panel_*.dtsi`（由驱动目录 include） | `qcom/mido/dsi-panel-*.dtsi`（标准 qcom 写法） |
| defconfig | `arch/arm64/configs/`（c7 的 64 位配置在本分支已被裁剪，需自建） | `arch/arm64/configs/mido_defconfig`（**直接拿来当底**） |
| Makefile | `arch/arm64/boot/dts/samsung/msm8953/Makefile` | `arch/arm64/boot/dts/qcom/Makefile`（要加 `dtb-$(CONFIG_ARCH_...) += ...`） |

**建议**：在 4.9 树里新建 `arch/arm64/boot/dts/qcom/samsung-c7lte/`，把 C7 的文件放进去，
include 路径改成 `../msm8953.dtsi`，并在 `qcom/Makefile` 里加一行 `dtb-$(CONFIG_ARCH_QCOM) += samsung-c7lte/msm8953-sec-c7lte_chn-r04.dtb`。

## 1. 头文件与 include 路径

3.18（`kernel/dts-3.18-source/msm8953-sec-c7lte_chn-r04.dts` 实测）：

```dts
/dts-v1/;
#include "../../qcom/msm8953.dtsi"
#include "msm-sec-audio.dtsi"
#include "msm8953-sec-common.dtsi"
#include "msm8953-sec-c7lte_chn-pinctrl-r02.dtsi"
#include "msm8953-sec-c7lte_chn-battery-r00.dtsi"
#include "msm8953-sec-msm8953lte-chn-fingerprint-sensor_00.dtsi"
#include "msm8953-camera-sensor-cdp-chn-r01.dtsi"
#include "../../../../../../drivers/video/msm/mdss/samsung/S6E3FA3_AMS568HN31/dsi_panel_..._cmd.dtsi"
/ { model = "Samsung Electronics. c7lte_chn";
    compatible = "qcom,msm8953-mtp", "qcom,msm8953", "qcom,mtp"; };
```

4.9 里要做的事：

1. `msm8953.dtsi` 改成相对路径（目录层级变了）；
2. **面板 dtsi 不要再用 `../../../../../../drivers/...` 这种跨目录 include**（4.9 树里驱动目录结构不同），
   把 `<PANEL>/dsi_panel_*.dtsi` 拷到 dts 目录旁边再 include；
3. `msm-sec-audio.dtsi` / `msm8953-sec-msm8953lte-chn-fingerprint-sensor_00.dtsi` /
   `msm8953-camera-sensor-cdp-chn-r01.dtsi` 也要一并从 3.18 树里拿过来（本仓库只放了其中 4 个，
   其余按文件名从三星树取：`arch/arm64/boot/dts/samsung/msm8953/`）。

## 2. pinctrl：3.18 的旧式属性要换成 4.9 的标准写法

3.18 三星的引脚配置用的是**定制属性**（`qcom,pins`/`qcom,num-grp-pins`/`qcom,pin-func`），
4.9 的 msm8953 树用的是**标准 pinctrl 绑定**：

```dts
/* 4.9 写法（参考 kernel/mido-4.9-reference/.../msm8953-pinctrl.dtsi） */
&tlmm {
    ts_int_active: ts_int_active {
        mux { pins = "gpio65"; function = "gpio"; };
        config { pins = "gpio65"; drive-strength = <8>; bias-pull-up; };
    };
};
/* 3.18 写法（c7 的 pinctrl dtsi 里） */
qcom,pins = <&tlmm 65>;
qcom,num-grp-pins = <1>;
qcom,pin-func = <0>;
```

**转换规则**：

| 3.18 | 4.9 |
|---|---|
| `qcom,pins = <&tlmm N>` | `pins = "gpioN"` |
| `qcom,num-grp-pins = <M>` | 去掉（`pins` 里逐个列出） |
| `qcom,pin-func = <F>` | `function = "gpio"` / `"blsp_i2c3"` / … |
| `bias-pull-up` / `qcom,pu` 类 | `bias-pull-up` / `bias-disable` / `bias-pull-down` |
| `drive-strength = <N>` | 同（单位 mA 档位，SDM 系列沿用） |

> c7 的 `msm8953-sec-c7lte_chn-pinctrl-r02.dtsi` 有 33 KB，是整个移植里**最机械但最容易漏**的一块，
> 建议先只转"面板 + 触摸 + I2C + UART"需要的引脚，能亮屏后再补其余。

## 3. I2C / SPI 设备：从"挂载点内声明"改成"引用式覆盖"

3.18 三星把这些设备直接写在 `&soc { i2c_3: i2c@78b7000 { ... } }` 里；
4.9 树里对应节点已经在 `msm8953.dtsi` 中定义好，板级文件只需要 `&i2c_3` 追加：

```dts
/* 4.9 */
&i2c_3 {
    status = "okay";
    touchscreen@20 {
        compatible = "imagis,ist3038h";   /* ← 用 C7 实际触摸 IC 的 compatible */
        reg = <0x20>;
        interrupt-parent = <&tlmm>;
        interrupts = <65 0x2002>;
        vdd-supply = <&pm8953_l10>;
        pinctrl-names = "pmx_ts_active","pmx_ts_suspend";
        pinctrl-0 = <&ts_int_active &ts_reset_active>;
    };
};
```

**C7 实测触摸 IC 是 MELFAS MMS449**（见 `c7-reference-defconfig-3.18.txt` 里的
`CONFIG_TOUCHSCREEN_MELFAS_MMS449=y`），所以 i2c 节点的 `compatible` 要对齐
`drivers/input/touchscreen/` 里 melfas 驱动的 `of_device_id`。

**注意**：`compatible` 必须与你要搬的触摸驱动里的 `of_device_id` 表一致；
C7 具体用哪颗触摸 IC，从 `msm8953-sec-c7lte_chn-pinctrl-r02.dtsi` 里 i2c 地址 +
`sec_ts`/`imagis`/`stm` 哪个驱动的 DTS 能对上确定。

## 4. 面板：三星定制 mdss 与标准 qcom mdss 的差别（最难的一块）

- 3.18 C7：`&mdss_mdp { ss_dsi_panel_S6E3FA3_AMS568HN31_FHD { qcom,mdss-dsi-panel-name = "ss_dsi_panel_..."; ... } }`
  ——`ss_` 前缀意味着**三星魔改过的 mdss 驱动**（`mdss_samsung_*` 那一大票函数、`SVC_OCTA`、
  `mdss_samsung_get_vdd`、温度补偿/亮度表等），标准 msm-4.9 里没有。
- 4.9 mido：`&mdss_mdp { qcom,mdss_dsi_nt35596_fhd_video { qcom,mdss-dsi-panel-name = "..."; ... } }`
  ——标准 qcom 面板节点。

**两条路线**（建议先 A）：

| 路线 | 做法 | 代价 |
|---|---|---|
| **A. 搬三星 mdss** | 把三星 3.18 的 `drivers/video/msm/mdss/` 里的三星扩展（`samsung/` 目录 + `mdss_samsung_*`）整体移植到 4.9 的 `drivers/video/msm/mdss/`，保留 `ss_dsi_panel_*` 写法 | 工作量大但面板特性（亮度表/温度补偿/HBM）完整 |
| **B. 改用标准 qcom 面板节点** | 只把 C7 面板的**时序/初始化序列**（`qcom,mdss-dsi-on-command`、`-timing`、`-porch`、`-clock-rate`）搬成 4.9 标准节点的属性，丢掉三星私有特性 | 上手快，可能亮度/色彩/护眼模式不完美 |

C7 面板关键参数（从 `kernel/dts-3.18-source/dsi_panel_S6E3FA3_AMS568HN31_fhd_octa_cmd.dtsi` 读到）：

```
面板名   ss_dsi_panel_S6E3FA3_AMS568HN31_FHD
分辨率   1080 x 1920，bpp 24
控制器   <&mdss_dsi0>
```

（其余的 porch/clock/初始化命令序列都在同一个文件里，逐条搬即可。）

## 5. 供电 / 时钟 / 互联

| 类型 | 3.18 | 4.9 | 备注 |
|---|---|---|---|
| 稳压器 | `regulator@X { qcom,init-voltage = <V>; }` | `&pm8953_lN { regulator-min-microvolt/max-microvolt; qcom,init-voltage = <V>; }` | 名称从 `pm8953_l10` 这类 phandle 直接引用 |
| 时钟 | `clocks = <&clock_gcc clk_gcc_blsp1_ahb_clk>` | 同名 phandle，但**时钟 ID 宏在 4.9 头文件里可能改名/改号** | 编译报错时按名字在 `include/dt-bindings/clock/qcom,gcc-msm8953.h` 里找 |
| 互联 | 3.18 无（总线带宽用 `qcom,bus-*`） | 4.9 有 `interconnect`/`qcom,msm-bus-*` | 先全删也能跑，性能后续再补 |
| 内存/chosen | 基本一致 | 基本一致 | 直接搬 |

## 6. 电池 / 充电 / 传感器中枢 / 指纹

这四个都是**三星私有驱动 + 对应 dtsi**，做法统一：

1. 驱动搬过去（路径见 `kernel/README.md` 的表）；
2. dtsi 里把 `compatible` 换成该驱动 `of_device_id` 里的字符串；
3. 引脚/i2c/spi 引用按第 2、3 节改；
4. 电池数据（`msm8953-sec-c7lte_chn-battery-r00.dtsi`）通常只是 `qcom,battery-data` 里的一串
   `batterydata-*` 引用，把对应的 `batterydata-*.dtsi` 也拷过来（mido 树里是 `qcom/mido/batterydata-*.dtsi` 的形式）。

## 7. defconfig

以 `kernel/mido-4.9-reference/arch/arm64/configs/mido_defconfig` 为底，追加/确认这些：

```
CONFIG_ARCH_QCOM=y
CONFIG_ARCH_MSM8953=y                # 依 4.9 树实际符号名
CONFIG_ANDROID_BINDER_IPC=y
CONFIG_ANDROID_BINDERFS=y            # Android 15 需要
CONFIG_BPF_SYSCALL=y
CONFIG_BPF_JIT=y
CONFIG_CGROUP_BPF=y
CONFIG_MEMFD_CREATE=y
CONFIG_ION=y                         # LOS 22.2 的 msm8953 仍用 ION
# C7 外设（符号名以驱动 Kconfig 为准）
CONFIG_SEC_TS=y / CONFIG_TOUCHSCREEN_IMAGIS=y
CONFIG_BHY=y
CONFIG_SEC_BATTERY=y
CONFIG_TFA989x=y
CONFIG_FINGERPRINT_* =y
CONFIG_DRM_MSM / CONFIG_FB_MSM_MDSS_SAMSUNG=y   # 视路线 A/B
```

用法：`make O=out ARCH=arm64 mido_defconfig` 起来之后，用 `scripts/config --enable ...` 或
`make O=out menuconfig` 增改，最后 `make O=out savedefconfig` 生成干净的 `c7ltechn_defconfig`。

> **起点已经有了**（两个补丁，依次 `git am`）：
> - `0001` 板级骨架（DTB 编译通过）
> - `0002` C7 引脚配置（`tools/dts-pinctrl-318to49.py` 从 3.18 自动转换的 60 个 C7 专属 pin state）
>
> 也就是说本手册第 2 节（pinctrl 转换）**已经做完了**，可以直接从第 3 节（i2c 设备）往下做。
>
> 原说明：：`kernel/patches/0001-arm64-dts-qcom-add-msm8953-c7ltechn-board-scaffold.patch`
> 是本工程做好的 C7 板级骨架（已在 4.9.337 树上编译通过，DTB 234940 字节，
> `qcom,board-id=<8 4>`），把它 `git am` 进去，然后按下面清单往里填外设。

## 8. 增量验证清单（每步都只在真机上刷 boot，不动 system）

| 步骤 | 期望现象 | 判据 |
|---|---|---|
| DTS 能编过 | 生成 `msm8953-sec-c7lte_chn-r04.dtb` | `make ... dtbs` |
| 内核能起来 | 串口/last_kmsg 有 `Linux version 4.9.x` | `/sys/fs/pstore/console-ramoops` |
| 存储 + UART OK | `init` 能挂 `/system`，进 recovery 界面 | TWRP 能用 |
| 面板 OK | 开机 logo / TWRP 画面正常 | 目视 |
| 触摸 OK | TWRP 能点 | 目视 |
| 其余 | 见 `docs/05-已知问题与调试.md` | — |
