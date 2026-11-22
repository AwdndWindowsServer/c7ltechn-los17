# 触摸（MELFAS MMS449）方案：改用主线 MIP4 驱动 —— 已落地

## 0. 结论（一句话）

C7 的触摸芯片 MMS449 属 **MELFAS MIP4 协议族**；三星**没有公开** `melfas,mms_ts` 的源码，
所以本工程改用**主线 Linux 的 `melfas_mip4.c`**，并且**必须取 v4.14 那一版**（不是 master）。
它已作为**补丁 0011** 进入补丁序列，编译链接通过、已进最终卡刷包的内核镜像。

```
kernel/patches/0011-input-touchscreen-use-upstream-mip4-driver.patch
```

---

## 1. 为什么不能用三星自己的驱动（检索证据）

| 检查对象 | 结果 |
|---|---|
| `Galaxy-MSM8953/android_kernel_samsung_msm8953`（lineage-16.0 / bak-2 / staging） | 只有 `mms114.c`（老 MMS114 芯片）与 `melfas_mip4/`（**触摸键** MHS204），**没有** `melfas,mms_ts` 触摸屏驱动 |
| `Wzedlare/android_kernel_samsung_msm8953`（2026 年的 fork） | 同样只有 `mms114.c`；相机 sensor 也没有 |
| `agx7p/...`、`PsychoGame/...` 等 fork | 同源，同样没有 |
| 原厂 dump 的 `/system/lib/modules` 与 `/system/etc/firmware` | 没有任何触摸驱动模块、**也没有触摸固件**（`tsp_melfas/*` 不存在） → 说明驱动与固件都是**编进/烧进原厂内核与芯片**的，源码没随开源包放出 |

> 这条"公开树里没有 MMS449 源码"的结论在多轮、多来源核实后固化在这里，不再重复检索。

---

## 2. 选型：主线 MIP4，且必须用 **v4.14** 版（同代原则的又一次验证）

| 版本 | 行数 | 在 4.9 上的实测结果 |
|---|---|---|
| `torvalds/linux` **master**（测试时是 6.x） | 1559 | **31 个错误**：`__free(kfree)` 清理属性、`guard()`、`dev_groups`、`dev_err_probe()`、`DEFINE_SIMPLE_DEV_PM_OPS`、`input_mt_report_slot_inactive()`、for 循环内声明（4.9 是 gnu89）等 —— 都是 master 才有的新 API |
| `torvalds/linux` **v4.14** | 1631 | **0 error**：只需把 `linux/unaligned.h` 换成 `asm/unaligned.h` |

v4.14 与 4.9 是同代代码，`devm_gpiod_get_optional` / `device_property_*` / `input_mt_*` 全都在。
本目录的 `melfas_mip4.c` 现在是 **v4.14 版（MIP 4.0 Rev 5.4）**。

### 另一个重要发现：mido 的 4.9 树本来就带一份旧版

zeelog 的 mido 4.9 树里**已经有** `drivers/input/touchscreen/melfas_mip4.c`（**Rev 4.6**），
Kconfig（`TOUCHSCREEN_MELFAS_MIP4`）与 Makefile 条目也都在。
所以补丁 0011 **不是新增文件，而是把 Rev 4.6 同步到 Rev 5.4**。5.4 相对 4.6 多出：

- 上电前先用 `i2c_smbus_xfer` 探一下从地址在不在（探不到**不算致命错误**）；
- 读 `product_id` / `VID` / `PID` / `slave_addr`（`0x7C`/`0x7E`/`0x80` 寄存器），填 `input->id.product`；
- 固件解析路径更完整（`mip4_parse_firmware`）。

---

## 3. 落地形态（补丁 0011 改了什么）

| 文件 | 改动 |
|---|---|
| `drivers/input/touchscreen/melfas_mip4.c` | Rev 4.6 → **Rev 5.4**（v4.14 原文，1631 行，仅 `unaligned.h` 一处适配） |
| `arch/arm64/boot/dts/qcom/msm8953-c7ltechn.dts` | `compatible = "melfas,mip4_ts", "melfas,mms_ts"`（并列保留三星 original，方便日后换回）+ `ce-gpios = <&tlmm 95 0>` |
| `arch/arm64/configs/c7ltechn_defconfig` | `CONFIG_TOUCHSCREEN_MELFAS_MIP4=y` |

**主线驱动到底读哪些 DTS 属性**（实测：整个驱动只有一处属性解析）：

```
ts->gpio_ce = devm_gpiod_get_optional(&client->dev, "ce", GPIOD_OUT_LOW);   // = ce-gpios
```

其余全部**从芯片读**：分辨率（`max_x/max_y`、`ppm_x/ppm_y`）、按键数与键值，都来自
`mip4_query_device()` 读回的 R1 info 区。中断走 I2C client 的 `client->irq`（即 DTS 的 `interrupts = <59 0x0>`）。
**没有** regulator 依赖（`mip4_power_on()` 只拉 `ce` 脚）。

所以我们的节点（补丁 0003 建、0011 补）**已经够了**：
`reg = <0x48>`、`interrupts = <59 0x0>`、`ce-gpios = <&tlmm 95 0>`，
外加 `tsp_int_active/suspend` 两个 pinctrl state。
节点里那些 `melfas,vdd_en` / `melfas,irq-gpio` / `melfas,max_x` … 对主线驱动是**惰性属性**（不读，也不报错），
保留它们纯粹是为了日后换回三星驱动时不用再写一遍。

---

## 4. 固件：probe 路径**不需要**固件 blob

- 主线驱动只在 **sysfs `update_fw`** 被写入时才 `request_firmware(ts->fw_name, ...)`
  （固件名默认 `melfas/mip4_<...>.bin`），probe 路径只是查询芯片信息 → **缺固件不影响 probe**。
- 原厂 `system` 里本来就没有触摸固件（见 §1 表），说明 C7 的触摸固件**在芯片里/由原厂内核烧录**。
- 因此我们**不需要**往 ROM 里塞触摸固件；若日后要升级固件，再把 blob 放到 `/vendor/firmware/melfas/`
  （注意：按 Android 15 的 `plat_file_contexts`，`/system/etc/firmware` 没有规则 → 我们统一镜像到
  `/vendor/firmware/`，那里的标签是 `u:object_r:vendor_firmware_file:s0`）。

---

## 5. 复现命令

```bash
# 方式 A（推荐，等价于补丁序列）：直接应用补丁
git am kernel/patches/0011-input-touchscreen-use-upstream-mip4-driver.patch

# 方式 B：脚本（幂等；与补丁 A 内容一致，实测两者产出的文件逐字节相同）
bash tools/touch-mip4-setup.sh work/kernel-4.9

# 单独验证编译
cd work/kernel-4.9
make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     CROSS_COMPILE_ARM32=arm-linux-gnueabi- drivers/input/touchscreen/melfas_mip4.o
```

已实测的证据：`melfas_mip4.o` 编译 0 error；`Image` 内有 MIP4 字符串；`vmlinux` 有 **26 个 mip4 符号**。

---

## 6. 只能真机验证的部分（诚实清单）

没有 C7 真机之前，以下都**不能算验证通过**：

| 项 | 风险 |
|---|---|
| 协议修订匹配 | 若 C7 芯片固件的 MIP4 修订太老、不响应 R1 info 命令，`mip4_query_device()` 会失败 → probe 失败 |
| 坐标方向/分辨率 | 分辨率从芯片读，但 X/Y 是否需要 swap/镜像只能上手看 |
| 按键（菜单/返回） | 键值来自芯片 info 区；若与原厂布局不符需在 DTS `linux,keycodes` 里改 |
| 中断与 LPM | `melfas,support_lpm`（三星的低功耗手势）主线驱动**不支持**；sleep 时按主线流程断电 |
| ESD/复位 | 三星驱动有 ESD 检测（原 DTS 里那个 65 号脚其实是**面板 ESD**，不是触摸 IRQ）；主线驱动没有这块，第一版靠面板侧的 ESD 处理 |

出问题时的退路（按顺序）：

1. 把 `compatible` 顺序调回三星项、换回 mido 树自带的 Rev 4.6 驱动对比；
2. 用 `i2cdetect`/`i2cget` 在 TWRP 下手动确认 0x48 是否应答、`ce-gpios 95` 是否拉高；
3. 最后才是"对照原厂内核反推协议"（成本最高，已确认公开源码不存在）。

---

## 7. 相关

- `kernel/patches/0011-input-touchscreen-use-upstream-mip4-driver.patch` —— 落地补丁
- `tools/touch-mip4-setup.sh` —— 幂等安装脚本（等价于补丁）
- `kernel/STATUS.md` —— 内核侧总状态
- `kernel/driver-availability.md` —— 各外设驱动的可得性/难度总表
