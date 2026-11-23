# LineageOS 17.1 for Samsung Galaxy C7 (SM-C7000 / c7ltechn)

把 **LineageOS 17.1（Android 10）** 移植到三星 Galaxy C7（SM-C7000，高通 MSM8953 / SD625）。
目标是一台能**正常开机进桌面**的 C7：显示、触摸、Wi-Fi、蓝牙、音频、相机、传感器、充电按真机日志逐项调通。

> 纯移植（port），不编译 LineageOS 源码。做法是借用一台**同 SoC、同为非 Treble** 的机器
> （红米 Note 4 / mido 的 LineageOS 17.1）的 Android 10 用户态，换上 C7 自己的 **Linux 4.9.337 内核**
> 和 C7 的 QCDT/DTB，再按 C7 的分区表重新打包。

当前状态：**第一个可刷包已由 CI 产出，等待真机验证**。

最新产物（2026-11-22，run [45054168073](https://github.com/AwdndWindowsServer/c7ltechn-los17/actions/runs/45054168073)）：

| 文件 | 大小 | 用途 |
| --- | --- | --- |
| `c7ltechn-port-odin-20261122.tar.md5` | 3.6 GB | 搞机助手/Odin 的 AP 槽 |
| `lineage-17.1-c7ltechn-port-20261122-UNOFFICIAL-kernel4.9.337.zip` | 699 MB | TWRP 卡刷 |
| `boot.img` | 13.8 MB | 单独刷 boot |

静态体检结论：硬性问题 0 项；system.img 3.59 GiB 正好放进 C7 SYSTEM（余 4 MiB）；所有文件带 SELinux 标签；
boot.img 为三星 v0 头 + QCDT（`msm_id=293`、`board_id=8`、subtype `0/3/4`）+ `SEANDROIDENFORCE`。
原厂闭源 blob 来自 [c7ltechn-blobs](https://github.com/AwdndWindowsServer/c7ltechn-blobs)，关键三星文件 11/15 在位。

---

## 一、三层结构

| 层 | 来源 | 说明 |
| --- | --- | --- |
| 内核 | `zeelog/android_kernel_xiaomi_mido` @ `lineage-22.2` + `kernel/patches/0001..0015` + 三星面板框架 | 4.9.337，带 C7 的 DTS（`msm8953-c7ltechn`）、S6E3FA3 面板、MMS449 触摸、SM5705 充电、BHY 传感器、RT5659 音频 |
| Android 用户态 | mido LineageOS 17.1（`lineage-17.1-20200505-UNOFFICIAL-mido.zip`） | 同 SoC 的 Android 10，非 Treble，vendor 在 system 内，和 C7 的分区习惯一致 |
| 打包 | `port/*.sh` + `tools/mkboot.py` + `tools/mkqcdt.py` | 重组 system.img、重打三星 v0 boot.img（dt 区放 QCDT 表），出 TWRP 卡刷包 / Odin tar |

为什么内核必须自己编：C7 的面板是三星的 S6E3FA3（AMS598KH01），触摸是 Melfas MMS449，
上游/小米内核都没有这些驱动；而三星 aboot 又会按 boot.img 的 **dt(QCDT) 区**里的
`qcom,msm-id` / `qcom,board-id` 选 DTB —— 用 donor 的 dt 区只会选到 mido 的板子，结果是黑屏重启。

---

## 二、仓库结构

```
kernel/       C7 内核补丁（0001..0015）、三星面板驱动源码、defconfig fragment、STATUS.md
port/         移植流水线：config.sh / 20-unpack.sh / 30-assemble-system.sh / 40-make-bootimg.sh / 50-make-zip.sh
tools/        bootimg.py（拆/打 boot.img）、mkboot.py（三星 v0 头）、mkqcdt.py（QCDT v2）、sdat2img.py、audit-image.py…
docs/         移植架构、刷机与排障
.github/workflows/
    kernel.yml   只编内核（可用 kernel_artifact_run 复用产物）
    build.yml    编内核 + 组装 system + 打 boot + 出卡刷包/odin 包，一条流水线
```

---

## 三、在 CI 上构建

`Actions → build-los17 → Run workflow`，输入：

| 输入 | 默认 | 说明 |
| --- | --- | --- |
| `kernel_artifact_run` | 空 | 填某次 `kernel-c7-4.9` 的 run_id 可跳过编内核（省 1 小时） |
| `donor_url` | 空 | 留空用 mido LOS17.1；换 donor 时填直链 |
| `c7_blobs` | `0` | `1` = 叠加 C7 厂商 blob（rild、传感器、音频参数、相机标定…），需要 vendor tarball |
| `make_odin` | `1` | 额外生成 Odin/搞机助手 线刷 `tar.md5` |

产物 artifact `los17-c7-<run_number>`：

* `out/lineage-17.1-<date>-UNOFFICIAL-c7ltechn-port-kernel4.9.x.zip` —— TWRP 卡刷包（boot.img + system.img）
* `out/c7ltechn-port-odin-<date>.tar.md5` —— Odin/搞机助手 AP 线刷包
* `summary.md`、`audit` 输出、`KERNEL_VERSION`

---

## 四、刷机（两种方式）

前置：OEM 解锁（下载模式显示 `OEM LOCK: OFF`）、**先备份 EFS / modemst1 / modemst2 / persist**。

### 方式 A：TWRP 卡刷（默认、唯一交付形式）

1. 先装一次 recovery（PBRP/TWRP，一次即可）：Odin/搞机助手 **AP** 槽刷 `recovery.tar`
   （内含 `recovery.img`，写进 C7 的 RECOVERY 分区，32 MiB）。
2. 关机 → **电源 + Home + 音量加**，进 recovery（PBRP）。
3. 先 **清除 → 格式化 Data 分区**（首次必须），再 **安装** 选
   `lineage-17.1-c7ltechn-port-<date>-UNOFFICIAL-kernel4.9.337.zip`。
4. 刷完回主菜单 **重启系统**。

> 卡刷包只写 `boot` + `system` 两个分区，不动 bootloader / EFS / PERSIST / PARAM / MODEM / DSP。
> 提前在 recovery 里备份 EFS / modemst1 / modemst2 / persist。

### 方式 B：Odin 线刷（可选，需手动在 workflow 里打开 make_odin）

刷完首启 **3~10 分钟**（首次 dex2oat 很慢），屏幕会先出三星 logo，然后出现 Lineage 开机动画。

---

## 五、当前已知限制（第一版）

* 首版目标是「能亮能进桌面」：显示、触摸、USB、Wi-Fi 按驱动就绪情况逐个验证。
* 原厂 blob 默认按 `C7_BLOB_MODE=minimal` 叠加（传感器 HAL、相机 provider、音频参数、Wi-Fi/BHY 固件）；
  `libsec-ril*` 仍用 donor 的 RIL 栈，指纹 HAL 与 32 位 `libmm-qcamera.so` 未叠加（`C7_BLOB_MODE=full` 才全量）。
* 相机（三星 S5K3P3 系列标定）、指纹（与 NFC 共用 I2C）、双卡 RIL 需要真机日志继续调。
* 没有 Treble：vendor 全部在 `/system/vendor`，`/vendor` 是符号链接。
* 不修改 bootloader / EFS / PERSIST / PARAM / MODEM / DSP。

---

## 六、排障

| 现象 | 先看什么 |
| --- | --- |
| 黑屏、卡在三星 logo 后重启 | 内核/DTB 没被选中：`fastboot getvar` 或 TWRP 里看 `/proc/device-tree/model`；确认包内 boot.img 的 dt 区是 C7 的 QCDT |
| 进不了系统、卡开机动画 | `adb logcat` / `adb shell dmesg`；`/proc/last_kmsg`（重启后仍在） |
| 触摸没反应 | `dmesg | grep -i mms`；检查 i2c_7 0x48 是否有设备 |
| Wi-Fi 打不开 | `dmesg | grep -i wcn`；需要 `wlan/prima` 固件与 MAC（本机 `wlan_mac.bin` 已从 stock 备份） |
| 无声音 | `dmesg | grep -i rt5659`；`tinymix` 看通路 |

详细流程见 [docs/01-移植架构.md](docs/01-移植架构.md)、[docs/02-刷机与排障.md](docs/02-刷机与排障.md)。
