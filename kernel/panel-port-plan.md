# 面板移植方案（三星 S6E3FA3 AMOLED → 4.9 CAF mdss）

> 这是整个内核移植里**最硬的一块**，也是"能不能用"的分水岭：屏幕不亮，别的都无从谈起。
> 本文把它的规模量出来，给出可执行的步骤，源料已经放好。

## 1. 现状与结论（先看这个）

| 问题 | 实测答案 |
|---|---|
| 4.9 树的显示驱动在哪？ | `drivers/video/fbdev/msm/`（**不是** `drivers/video/msm/mdss/`，4.9 挪过位置） |
| 两边是同一套驱动吗？ | 是。都是 CAF mdss **fbdev**（不是 DRM），mido 4.9 的 defconfig 就是 `CONFIG_FB_MSM_MDSS=y` |
| 差多少？ | 见下表，同一个文件差几百行，属于"可移植的增量"，不是重写 |
| 三星的改动点在哪？ | `mdss_dsi_panel.c` 里有 **22 处** `samsung_*` 挂钩（4.9 版里 = 0 处） |
| 面板驱动本体多大？ | C7 面板 981 行（`ss_dsi_panel_S6E3FA3_AMS598KH01.c`）+ smart_dimming + mdnie |
| 框架多大？ | 顶层 `samsung/` 有 11 个 .c（共 ~2.3 万行）+ 13 个头文件/Kconfig/Makefile |

### 核心文件差异（行数 / diff 规模）

| 文件 | 三星 3.18 | mido 4.9 | 4.9 独有 | 三星独有 |
|---|---:|---:|---:|---:|
| `mdss_dsi_panel.c` | 3319 | 3027 | 185 | **477** |
| `mdss_dsi.c` | 4881 | 4578 | 278 | **581** |
| `mdss_fb.c` | 5309 | 5295 | 315 | 329 |
| `mdss_mdp.c` | 5102 | 5318 | 461 | 245 |

> "三星独有"那列就是**要搬过来的增量**（含三星面板框架的挂钩调用），规模可控。

## 2. 三星在 `mdss_dsi_panel.c` 里加的所有挂钩（照这个清单打）

```
samsung_get_vdd                        ×4      面板供电
samsung_display_driver_data            ×4      面板驱动数据表
samsung_power_pre_off_reset_delay      ×3      上/下电时序
samsung_power_on_reset_delay           ×3
samsung_power_off_reset_delay          ×3
samsung_wait_after_reset_delay         ×2
samsung_timing_engine_control          ×2      TE / 时序引擎
samsung_dsi_force_clock_lane_hs        ×1
ss_dsi_panel_common                    ×1      面板公共层入口
```

（`mdss_dsi.c` / `mdss_fb.c` 里还有同类挂钩，移植时用同样的方法逐个 grep 出来即可。）

## 3. 源料（已放进本仓库）

```
kernel/panel-3.18-source/
├── S6E3FA3_AMS598KH01/          ← C7 r04 用的面板（主目标）
│   ├── ss_dsi_panel_S6E3FA3_AMS598KH01.c/.h        981 行
│   ├── ss_dsi_smart_dimming_S6E3FA3_AMS598KH01.c/.h
│   ├── ss_dsi_mdnie_S6E3FA3_AMS598KH01.h
│   └── dsi_panel_S6E3FA3_AMS598KH01_fhd_octa_cmd.dtsi   ← 面板 DTS（时序/初始化序列）
├── S6E3FA3_AMS568HN31/          ← 另一版本面板（C7 早期批次）
└── *.c/*.h/Kconfig/Makefile     ← 三星面板框架（11 个 .c）
      ss_dsi_panel_common / ss_dsi_panel_sysfs / ss_dsi_panel_debug /
      ss_dsi_smart_dimming_common / ss_dsi_mdnie_lite_common /
      ss_regulator_common / ss_self_display_common / ss_ddi_poc_common /
      ss_ddi_spi_common / ss_dpui_common / dlog
```

## 4. 移植步骤（建议顺序）

```
① DTS 前置（已完成）
   C7 的显示引脚是 mdss_dsi gpio(50,94)，与 4.9 基线(59,61)不同 ——
   已在补丁 0008 里作为 c7_mdss_dsi_active/suspend 找回。
   面板 DTS 用面板目录里的 dsi_panel_*.dtsi（时序/初始化序列原样搬）。

② 先把 4.9 的 mdss 编过并让它认识"外部面板"
   - 把 kernel/panel-3.18-source 的框架文件放进 drivers/video/fbdev/msm/samsung/
   - 在 fbdev/msm/Kconfig + Makefile 里挂上（参照 3.18 的 samsung/Kconfig）
   - 这一步会暴露一大堆 API 差异 —— 这份"编译错误清单"就是移植的 punch list

③ 按第 2 节清单，把 samsung_* 挂钩补进 4.9 的 mdss_dsi_panel.c
   （建议逐个挂钩小步提交，每步都保证能编过）

④ 面板驱动适配：ss_dsi_panel_S6E3FA3_AMS598KH01.c 的 981 行里，
   主要依赖 mdss_samsung_panel_data_read（×8）与框架提供的 ss_panel_* 结构

⑤ 最后打通 mdss_dsi.c / mdss_fb.c 里的同类挂钩

⑥ 真机验证顺序：TWRP 能显示 → 开机 logo → bootanimation → 桌面
   （TWRP 用的是 4.9 内核 + 同一套 mdss，能显示 TWRP 就说明面板链路通了）
```

## 5. 备选方案（如果三星 mdss 移植受阻）

**路线 B：改用标准 qcom 面板节点**，只搬 C7 面板的时序/初始化序列
（`qcom,mdss-dsi-on-command`、`-timing`、`-porch`、`-clock-rate` 等，都在
`dsi_panel_S6E3FA3_AMS598KH01_fhd_octa_cmd.dtsi` 里），丢掉三星私有的
亮度表 / 温度补偿 / mdnie / 智能调光。

- 优点：不用动 mdss 核心，工作量小一个数量级；能亮屏、能进系统
- 缺点：亮度曲线、护眼模式、AOD 之类会不对
- 建议：**先用路线 B 把系统跑起来，再回头做路线 A**（两者 DTS 可以共存，用哪个由
  `qcom,dsi-pref-prim-pan` 指向谁决定）

## 6. 风险提示

1. mdss 是**最复杂**的子系统（MDP/DSI/PHY/时钟/电源域交织），改错的表现往往是黑屏无 log，
   排查成本高 → 建议**小步提交 + 每步单独编过**。
2. 三星面板框架与 4.9 mdss 的**结构体字段**可能不同（如 `struct mdss_panel_data`），
   这类差异编译期就能发现，但要一个个补。
3. 面板初始化序列里的 DSI 命令是**照面板规格书来的**，这部分**不要改**，原样搬。

---

## 7. 进度记录（第 13 轮实测）

### 已完成

1. **框架装进 4.9 树**：`tools/panel-framework-setup.sh`（幂等）+ `tools/panel-framework-fixes.py`
   （每条修补都对应一个真实编译错误）
2. **接口修补清单（9 类，全部实测）**

| # | 问题 | 修法 |
|---|---|---|
| 1 | `<linux/sync.h>` / `<linux/sw_sync.h>` 在 4.9 已移除 | 删掉 include（用到 sync 的代码本来就是 `#if 0`） |
| 2 | `debugfs_create_bool` 第 4 参数 4.9 改成 `bool *` | `(u32 *)` 强转改 `(bool *)`（字段本来就是 bool） |
| 3 | `of_get_regulator_init_data()` 4.9 多一个参数 | 补 `NULL` |
| 4 | `struct dsi_panel_cmds` 缺 `read_size/read_startoffset/name` | 加字段（`CONFIG_FB_MSM_MDSS_SAMSUNG` 守卫） |
| 5 | `struct mdss_dsi_ctrl_pdata` 缺 `event_handler` | 加字段 |
| 6 | DSI ESD 枚举缺 `ESD_REG_IRQ` | 补枚举值 |
| 7 | `struct mdss_panel_data` 缺 `panel_private` | 加字段 |
| 8 | `struct mdss_panel_info` 缺 `panel_state`（`blank_state` 4.9 已有，不能重复加） | 加字段 |
| 9 | 缺 `MDSS_SAMSUNG_EVENT_*`、`CMD_REQ_BROADCAST`、`struct debug_log`（+`debug_data.logd`） | 全部补上 |
| 10 | 缺头文件 `linux/self_display/self_display.h`（在 uapi 下）、`sec_debug*.h` | 从三星树补 |

3. **框架编译结果**：`drivers/video/fbdev/msm/samsung/` **7/11 个 .o 编译通过，0 error**
   （未编的 4 个由 config 关闭：dlog / dpui / ddi_poc / ddi_spi）

### 下一步（punch list）

1. **面板 .c 与框架头版本不一致**（本轮实测发现）：`ss_dsi_panel_S6E3FA3_AMS598KH01.c` 用到
   `struct samsung_display_dtsi_data` 的 `manufacture_date_rx_cmds` / `ddi_id_rx_cmds` /
   `cell_id_rx_cmds` 以及枚举 `PANEL_LEVE2_KEY`（三星原文就是这么拼的），
   但本树框架头里的该结构体**没有**这些成员 —— 说明面板驱动和框架头不是同一修订版。
   → 做法：按面板 .c 的期望把这些成员补进 `ss_dsi_panel_common.h`（同样用 config 守卫），
     或在三星 Kconfig 里找到打开它们的开关。
2. 打通 mdss 核心改造：`mdss_dsi.c` / `mdss_fb.c` 里的 `samsung_*` 挂钩
   （第 2 节已列出 `mdss_dsi_panel.c` 的 22 处），以及
   `mdss_samsung_parse_dcs_cmds` / `mdss_samsung_panel_cmd_read` 的实现。
3. 全量编译（`make Image.gz-dtb`）验证整树链接。

---

## 8. 第 14 轮实测：面板 .c 与框架头**版本不匹配**（重要结论）

把面板驱动单独编出来（`make .../S6E3FA3_AMS598KH01/ss_dsi_panel_S6E3FA3_AMS598KH01.o`）后，
用"自动补齐结构体成员"的办法把缺的命令表一次性找了出来：

```
struct samsung_display_dtsi_data: 框架头 48 个成员 / 面板+框架实际用到 62 个 → 缺 21 个
缺的是：gamma_tx_cmds、hbm_rx_cmds、hbm2_rx_cmds、hbm_gamma_tx_cmds、hbm_etc_tx_cmds、
        elvss_tx_cmds、elvss_rx_cmds、elvss_lowtemp_tx_cmds、aid_tx_cmds、
        acl_on/off/percent_tx_cmds、smart_acl_elvss_tx_cmds、mdnie_read_rx_cmds、
        smart_dimming_mtp_rx_cmds、panel_tx/rx_cmd_list …
```

把 21 个成员按同风格补上之后，暴露出**更深层的不匹配**（不是加字段能解决的）：

| 报错 | 含义 |
|---|---|
| `assignment to 'char (*)(...)' from 'int (*)(...)` | 本树框架里某个 ops 的函数指针类型与面板驱动期望的不同 |
| `implicit declaration of 'get_candela_value' / 'get_cmd_index'` | 面板驱动调用的这两个框架函数在**本版框架里根本不存在** |
| `struct mdnie_lite_tune_data` 从 `void *` 赋值 | `ss_dsi_mdnie_lite_common.h` 的结构体/接口与面板驱动期望的不同 |
| `struct candela_map_table` 没有 `lux_tab_size`（只有 `tab_size`） | 同上：candela 表结构体版本不同 |
| `subscripted value is neither array nor pointer` | 面板驱动把某个成员当数组用，本版框架里它不是数组 |

**结论**：公开的 `Galaxy-MSM8953/android_kernel_samsung_msm8953@lineage-16.0` 里那份
**面板框架（`ss_dsi_panel_common.h` 等）是较早的修订版**，而 C7 的面板驱动
（`ss_dsi_panel_S6E3FA3_AMS598KH01.c`）是较新的修订版。两者不是同一代。

### 两条出路（下一轮选一条）

| 方案 | 做法 | 评价 |
|---|---|---|
| **A. 找同代框架** | 到别的三星 msm8953 机型内核树里找**更新版**的 `ss_dsi_panel_common.*` / `ss_dsi_mdnie_lite_common.*` / `ss_dsi_smart_dimming_common.*`（比如同样用 S6E3FA3 系列的 C7 Pro / A6+ 树），整体替换框架 | 推荐：拿到的是一致的一套，省去逐个 back-port |
| **B. 反向适配面板驱动** | 按本版框架的 API 改面板驱动（`get_candela_value`→本版对应函数、`lux_tab_size`→`tab_size`、函数指针签名对齐…） | 改动集中在面板 .c 一处，但要逐条对着框架改，风险是漏改后行为不对 |

> 顺带把上一轮那个"PANEL_LEVE2_KEY / PANEL_LEVE1_KEY"的笔误也确认了：
> 面板驱动里共 5+ 处写成这两种拼法，本版框架的枚举值是 `LEVEL1_KEY` / `LEVEL2_KEY`
> —— 已按后者修正（已写入面板 .c 的注释）。

**框架侧仍然保持 7/11 对象、0 error**；面板 .c 在方案 A/B 落地前编不过，这是当前唯一卡点。

---

## 9. 第 15 轮：**面板驱动编译链接通过**（方案 A 成功）

按方案 A 去同仓库的**其它分支**找同代框架，一击命中：

| 分支 | `ss_dsi_panel_common.h` | manufacture_date_rx_cmds | hbm_rx_cmds | lux_tab_size | get_candela_value |
|---|---|---|---|---|---|
| `lineage-16.0`（原来用的） | 框架较旧 | ❌ | ❌ | ❌ | ❌ |
| **`bak-2` / `lineage-15.0`** | **框架较新，且自带 C7 面板** | ✅ | ✅ | ✅ | ✅ |

`bak-2` 的框架 `ss_dsi_panel_common.c` 有 **7399 行**（lineage-16.0 那份只有 4895 行），
而且**它自己就带 `S6E3FA3_AMS598KH01/`（C7 面板）** —— 说明这本来就是一整代匹配的代码。
另外上一轮以为是"三星笔误"的 `PANEL_LEVE1_KEY` / `PANEL_LEVE2_KEY`，
在 bak-2 里是**真实存在的枚举**（`PANEL_LEVE_KEY_*` 家族），当初的"笔误"判断只对旧框架成立。

**结果（实测）**

```
框架:  ss_dsi_panel_common.o  ss_dsi_mdnie_lite_common.o
       ss_dsi_smart_dimming_common.o  ss_regulator_common.o      → 4/4 全过
面板:  ss_dsi_panel_S6E3FA3_AMS598KH01.o        (398000 bytes)
       ss_dsi_smart_dimming_S6E3FA3_AMS598KH01.o (157376 bytes)
       built-in.o                                (552328 bytes)  ← 链接通过
```

**整套三星显示栈（框架 + C7 面板驱动）现在都能在 4.9 树上编译链接了。**

本轮追加的 3 处修补（都已写进 `tools/panel-framework-fixes.py`）：
1. `#include "../../mdss/xxx.h"` → `"../xxx.h"`（目录层级变了）
2. `debugfs_create_bool` 的 `(u32*)` 强转修正**扩展到 `ss_dsi_panel_common.c`**（bak-2 把代码挪到那里了）
3. `struct panel_func` 补 `samsung_force_acl_on`：框架里**没有任何地方调用**它，
   只有面板驱动赋值 → 按面板实现的真实签名 `int (*)(struct mdss_dsi_ctrl_pda *ctrl)` 声明

### 下一步

面板驱动本身通了，剩下的是**它依赖的 mdss 核心改造**：
`mdss_dsi.c` / `mdss_fb.c` / `mdss_dsi_panel.c` 里的 `samsung_*` 挂钩
（`mdss_dsi_panel.c` 的 22 处清单见第 2 节），以及
`mdss_samsung_parse_dcs_cmds` / `mdss_samsung_panel_cmd_read` 的实现
—— 这两类都在 bak-2 的核心 mdss 文件里，下一轮按同样的"取同代文件 + 编译验证"办法处理。

---

## 10. 第 16 轮：接口边界量清了 —— 只剩 **9 个符号 + 22 处挂钩**

用 `nm` 把"三星显示栈（框架 + C7 面板）已定义"与"需要外部提供"做集合差，
之前以为要补的一大堆，实际**只差 9 个符号**（此前的 14 个是同一批 object 合并统计导致的重复计数）：

| 需要的符号 | bak-2 里定义在 | 4.9 核心里是否已有同名实现 |
|---|---|---|
| `mdss_dsi_panel_cmds_send` | `mdss_dsi_panel.c` | ✅ 有（`mdss_dsi_panel.c`） |
| `mdss_dump_reg` | `mdss_debug_xlog.c` | ✅ 有 |
| `mdss_xlog` | `mdss_debug_xlog.c` | ✅ 有 |
| `mdss_fb_report_panel_dead` | `mdss_fb.c` | ✅ 有（`dsi_status_6g.c`） |
| `mdss_mdp_get_intf_base_addr` | `mdss_mdp_intf_video.c` | ✅ 有（`mdss_debug.c`） |
| `mdss_mdp_get_mdata` | `mdss_mdp.c` | ✅ 有（`mdss_debug.c`） |
| `mdss_mdp_panel` | —（应是变量/宏） | ✅ 有 |
| **`mdss_samsung_parse_dcs_cmds`** | `mdss_dsi_panel.c` | ❌ 需要移植 |
| **`mdss_samsung_panel_cmd_read`** | `mdss_dsi_panel.c` | ❌ 需要移植 |

**结论**：9 个里 **7 个在 4.9 核心里已经有同名实现**（之前显示"未定义"只是因为我只编了 samsung 子目录），
真正要移植的只有 **2 个三星函数**（都在 bak-2 的 `mdss_dsi_panel.c` 里）。

另外实测：4.9 的显示核心本身编译通过（`CC mdss_fb.o`，只有一个 frame-size 警告），
说明**核心与三星框架能在同一棵树里共存编译**。

### 真正的剩余工作（下一轮）

不是"编译对齐"，而是**让核心去调用三星框架**：
把 `mdss_dsi_panel.c` 的 **22 处 `samsung_*` 挂钩**（第 2 节清单）逐个补进 4.9 的核心，
并移植上面那 2 个函数。做完之后，面板才会真正被点亮流程调用到。
这属于"改核心"，建议按挂钩逐个小步提交，每步保证能编过。
