# mido-4.9-reference/ — 4.9 目标树的参考文件

这些文件从 [`zeelog/android_kernel_xiaomi_mido`](https://github.com/zeelog/android_kernel_xiaomi_mido)
`lineage-22.2` 分支（Linux **4.9.337**，Redmi Note 4 / MSM8953，跑 Android 15）里抠出来，
作为 C7 板级移植的**目标格式样板**（对照手册见 `../DTS-3.18-to-4.9.md`）：

| 文件 | 用途 |
|---|---|
| `arch/arm64/boot/dts/qcom/msm8953-mtp.dts` | 4.9 的板级主 DTS 长什么样 |
| `arch/arm64/boot/dts/qcom/msm8953-mtp.dtsi` | 板级公共节点（i2c/spi/regulator/panel 引用） |
| `arch/arm64/boot/dts/qcom/msm8953-pinctrl.dtsi` | **4.9 标准 pinctrl 写法**（`pins`/`function`/`bias-*`） |
| `arch/arm64/configs/mido_defconfig` | **defconfig 基底**，C7 的 defconfig 从这里改 |

要完整源码（编内核用）：

```bash
git clone --depth=1 -b lineage-22.2 https://github.com/zeelog/android_kernel_xiaomi_mido kernel-4.9
```

mido 4.9 树的另外两个有用位置：

- `arch/arm64/boot/dts/qcom/mido/` —— 设备私有 dtsi（面板 `dsi-panel-*.dtsi`、电池 `batterydata-*.dtsi`），
  这是 4.9 里"把设备私有 DTS 放子目录"的范例；
- `arch/arm64/configs/msm8953_defconfig` —— 纯 SoC 配置（不带小米设备项），做 C7 defconfig 的另一个底。
