# C7 外设驱动可得性清单（实测，不是估计）

来源：把公开的三星 3.18 内核树
（[`Galaxy-MSM8953/android_kernel_samsung_msm8953`](https://github.com/Galaxy-MSM8953/android_kernel_samsung_msm8953)
@`lineage-16.0`，59824 个文件）逐一核对，并与 `kernel/c7-reference-defconfig-3.18.txt`
（C7 国行真实设备配置）里的每一项对应。

## 1. 总表

| 功能 | C7 实际芯片 | 驱动在公开 3.18 树里？ | 具体位置 / 说明 |
|---|---|---|---|
| 显示面板 | S6E3FA3_AMS598KH01（r04）/ AMS568HN31 | ✅ 有 | `drivers/video/msm/mdss/samsung/S6E3FA3_AMS598KH01/`，配 `CONFIG_FB_MSM_MDSS_SAMSUNG`（三星魔改 mdss） |
| 触摸 | **MELFAS MMS449** | ❌ 三星树没有，**但有主线替代方案** | 树里只有 `drivers/input/touchscreen/mms114.c`，它的 compatible 只有 `melfas,mms114`，**不覆盖 `melfas,mms_ts`**；原厂也没编成模块（stock `/system/lib/modules` 只有测试模块） → 需从别的三星机型内核树取 |
| 触摸键 | ABOV MC96FT16xx | ✅ 有 | `drivers/input/keyboard/abov_touchkey_16xx.c`（`compatible = "abov,mc96ft16xx"` 完全对得上）**已移植并在 4.9 编译通过** |
| 指纹 | VFS7xxx（SPI4） | ✅ 有 | `drivers/fingerprint/vfs7xxx.c` + 框架 `drivers/fingerprint/`（同目录还有 et320/et510/et5xx 等其它型号） |
| 传感器中枢 | Broadcom BHI | ✅ 有 | `drivers/misc/bhy/`（`bhy_core.c`、`bhy_i2c.c`…） |
| 传感器框架 | — | ✅ 有 | `drivers/sensors/`（`sensors_core.c`、`sensors_ssc.c`，及 cm36672p / a96t3x6 / stk3x3x 等具体传感器） |
| 充电 | **SM5705** | ✅ 有 | `drivers/battery/sm5705_charger.c`、`sm5705_charger_oper.c`，头文件 `include/linux/battery/charger/sm5705_charger.h` |
| 电量计 | SM5705 | ✅ 有 | `drivers/battery/sm5705_fuelgauge.c` + `include/linux/battery/fuelgauge/sm5705_fuelgauge*.h` |
| MUIC | SM5705 | ✅ 有 | 驱动在 `drivers/battery/` 与 `drivers/mfd/` 一带（`muic-universal` 匹配）；三星还给了现成的 DTS 参考 `arch/arm64/boot/dts/samsung/msm8953/msm8953-sm5705.dtsi` |
| 闪光灯 | SM5705 FLED | ✅ 有 | `sm5705_fled`（`siliconmitus,sm5705-fled`）+ `include/linux/leds-sm5705.h` |
| NFC | PN548 | ✅ 有 | `drivers/nfc/pn547.c`（三星的 pn547 驱动同时覆盖 PN548 系列）+ `drivers/nfc/p61.c` |
| eSE | eSE P3 | ✅ 有 | `drivers/nfc/ese_p3.c` |
| 音频 codec | WCD（QC） | ✅ 有 | `sound/soc/codecs/wcd-mbhc-v2.c` 等 |
| 功放 | **TFA9897** | ⚠️ 只有近亲 | 树里是 `sound/soc/codecs/tfa9872/`（NXP TFA9872），C7 的 TFA9897 要么用同一家族的 tfa98xx 驱动魔改，要么另找 |
| 振动 | msm_vibrator | ⚠️ 需确认 | 树里有 `drivers/input/misc/pm8xxx-vibrator.c`；C7 DTS 里是 `msm_vibrator` 节点，具体驱动待核对 |
| 热敏电阻 | sec_thermistor | ✅ 有 | `drivers/hwmon/sec_thermistor.c` |
| 相机 sensor | s5k3p3sx / s5k3p8sx / s5k4h5yc / s5k5e3yx / sr846 / imx241 / imx258 / sr259 | ❌ **没有** | `drivers/media/platform/msm/camera_v2/sensor/` 里只有框架（`msm_sensor.c`/`msm_sensor_driver.c`/`msm_sensor_init.c`），**具体 sensor 驱动没随开源包放出**（只找到 `s5k5e3yx_otp.h` 一个头文件） |

## 2. 结论：内核移植的实际工作量分布

```
容易（驱动在手上，照补丁 0004 的模式搬）：
  触摸键 ABOV ✅已完成 · SM5705 充电/电量计/MUIC/闪光灯 · BHI 传感器中枢
  指纹 VFS7xxx · NFC(pn547/ese_p3) · sec_thermistor · 音频 codec

中等（要连框架一起搬或魔改）：
  显示面板 + 三星 mdss 扩展（工作量大但路径明确）
  TFA9897 功放（拿 tfa9872 改芯片 ID/寄存器）
  振动

需要外部源码（公开树里没有）：
  ① MELFAS MMS449 触摸驱动
  ② 相机 sensor 驱动（8 颗，量最大）
```

> 这两项缺失是三星开源包的"保留项"，不是我们没找到：`mms114.c` 的
> `of_device_id` 只有 `melfas,mms114`；camera_v2/sensor 目录里没有 C7 的任何一颗 sensor。
> 出路：从别的三星机型内核树（同样用 MMS449 / 同款 sensor 的机型）取驱动再适配。

---

## 3. 重要更新（第 22 轮）：MMS449 找到**主线替代驱动**

公开三星树里确实没有 `melfas,mms_ts` 触摸驱动（已核实 Galaxy-MSM8953 的 lineage-16.0 / bak-2 /
staging 分支，以及 2026 年的 fork `Wzedlare/...`；原厂 `/system/lib/modules` 里也没有模块，
说明是编进原厂内核但源码未公开）。

**但**：C7 的 MMS449 属于 **MELFAS MIP4 协议族**，而**主线 Linux 有完整的 MIP4 触摸屏驱动**：

```
drivers/input/touchscreen/melfas_mip4.c    1559 行, GPL-2.0-or-later
compatible = "melfas,mip4_ts"
```

已存档到 `kernel/melfas-mip4-mainline/`（含适配清单与落地步骤）。
实测它依赖的现代 API 很少（`devm_gpiod_get_optional`、`input_set_abs_params`、
`input_mt_init_slots` 4.9 都有），属于**可移植**的候选。

→ 结论从「❌ 无解，需外部源码」升级为「⚠️ 有主线驱动可用，需 backport 适配」。

相机 sensor 的情况仍无解（多个 fork 与公开树都只有框架，没有 C7 的任何一颗 sensor 驱动）。
