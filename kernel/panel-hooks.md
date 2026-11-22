# 面板挂钩清单（从 bak-2 的 mdss_dsi_panel.c 生成）

> 这些是"核心需要回头调用三星框架"的位置。4.9 的核心里目前一处都没有（0 处），
> 需要逐个补进 `drivers/video/fbdev/msm/mdss_dsi_panel.c`。

| 挂钩 | 次数 | 出现在哪些函数里 |
|---|---|---|
| `samsung_display_driver_data` | 3 | mdss_dsi_panel_reset, mdss_dsi_panel_on, mdss_dsi_panel_off |
| `samsung_get_vdd` | 3 | mdss_dsi_panel_reset, mdss_dsi_panel_on, mdss_dsi_panel_off |
| `samsung_power_on_reset_delay` | 3 | mdss_dsi_panel_reset |
| `samsung_power_off_reset_delay` | 3 | mdss_dsi_panel_reset |
| `samsung_timing_engine_control` | 2 | mdss_dsi_panel_on, mdss_dsi_panel_off |
| `samsung_wait_after_reset_delay` | 2 | mdss_dsi_panel_on |
| `ss_dsi_panel_common` | 1 | (file scope) |
| `samsung_dsi_force_clock_lane_hs` | 1 | mdss_dsi_panel_on |

**合计 18 处调用点，分布在 8 个挂钩上。**

## 建议顺序

1. `samsung_display_driver_data` / `samsung_get_vdd` —— 没有它们框架拿不到面板数据，等于没接上
2. 上/下电与 reset 时序（`*_reset_delay`、`wait_after_reset_delay`）—— 决定面板能不能被正确点亮
3. `ss_dsi_panel_common` —— 框架公共入口
4. `samsung_timing_engine_control`、`samsung_dsi_force_clock_lane_hs` —— TE/时钟，属于完善项

> 做法：从 bak-2 的 `mdss_dsi_panel.c` 里把这些调用点所在的代码块**原样搬过来**（同代代码，
> 结构体字段都对得上），每搬一类就编一次，保证 `mdss_dsi_panel.o` 始终能编过。

---

## 进度（第 18 轮）

### 已落地：`mdss_dsi_panel_reset` 的挂钩（第一批）

| 挂钩 | 状态 |
|---|---|
| `#include "samsung/ss_dsi_panel_common.h"`（拿 `samsung_get_vdd` 与面板数据结构） | ✅ 已加（config 守卫） |
| `struct samsung_display_driver_data *vdd = samsung_get_vdd();` | ✅ 已加 |
| 上电复位延时 `samsung_power_on_reset_delay` | ✅ 已加（disp_en 拉起之后） |
| 下电复位延时 `samsung_power_off_reset_delay` + `usleep_range(200,200)` | ✅ 已加（rst_gpio 拉低之后） |

配套的核心改动（必要，且与三星核心一致）：

```c
- static int mdss_dsi_panel_cmds_send(...)   /* 4.9 原本是 static */
+ int mdss_dsi_panel_cmds_send(...)          /* 三星框架要跨文件调用它 */
```
（不动这处会出现 `static declaration ... follows non-static declaration`，
因为框架头把它声明成了外部可见。）

**验证**：`mdss_dsi_panel.o` 编译通过；`nm` 显示
`T mdss_dsi_panel_cmds_send`（已导出）与 `U samsung_get_vdd`（由框架对象提供）。

### 待办（下一轮）

- `mdss_dsi_panel_on`：`samsung_get_vdd`、`samsung_wait_after_reset_delay`×2、`samsung_timing_engine_control`
- `mdss_dsi_panel_off`：`samsung_get_vdd`、`samsung_timing_engine_control`
- 文件作用域的 `ss_dsi_panel_common`（框架公共入口）

> 办法与第一批相同：从 bak-2 的 `mdss_dsi_panel.c` 拷对应代码块，每类编一次。

---

## 进度（第 19 轮）：`_on` / `_off` 挂钩落地

| 位置 | 插入内容 |
|---|---|
| `mdss_dsi_panel_on` 开头 | `struct samsung_display_driver_data *vdd = samsung_get_vdd();`（带 NULL 检查与警告） |
| `on_cmds` 发送**之前** | `mdss_samsung_panel_on_pre(pdata);` —— 面板初始化序列由三星框架发 |
| `on_cmds` 发送**之后** | `mdss_samsung_panel_on_post(pdata); pinfo->panel_state = true;` |
| `mdss_dsi_panel_off` 开头 | 同上 `vdd` 声明 |
| `off_cmds` 发送**之前** | `pinfo->blank_state = MDSS_PANEL_BLANK_BLANK; mdss_samsung_panel_off_pre(pdata);` |
| `off_cmds` 发送**之后** | `mdss_samsung_panel_off_post(pdata); pinfo->panel_state = false;` |

**验证**：`mdss_dsi_panel.o` 编译通过（0 error）；`nm -u` 显示对框架的
`mdss_samsung_panel_{on,off}_{pre,post}` **4 处引用**（由 `ss_dsi_panel_common.o` 提供）。

至此**点亮面板的关键链路已经接上**：
```
核心 mdss_dsi_panel_on/off
   → 三星框架 ss_dsi_panel_common.c
      → 具体面板 ss_dsi_panel_S6E3FA3_AMS598KH01.c（初始化序列/DTS 命令表）
```

### 仍未做（属于"完善项"，不影响基本点亮）

- `samsung_wait_after_reset_delay`（复位后等待，时序微调）
- `samsung_timing_engine_control`（TE/时序引擎，主要在 hall-IC 双屏场景用到）
- `samsung_dsi_force_clock_lane_hs`（强制 HS 时钟）
- hall-IC（翻盖）相关分支：C7 无此硬件，可不做
- 文件作用域的 `ss_dsi_panel_common` 入口（框架注册）

---

## 进度（第 21 轮）：挂钩清单**全部完成**

| 挂钩 | 状态 | 位置 |
|---|---|---|
| `samsung_get_vdd` | ✅ | reset / on / off 三处 |
| `samsung_power_on_reset_delay` | ✅ | `mdss_dsi_panel_reset` |
| `samsung_power_off_reset_delay` | ✅ | `mdss_dsi_panel_reset` |
| `mdss_samsung_panel_on_pre` / `_post` | ✅ | `mdss_dsi_panel_on` |
| `mdss_samsung_panel_off_pre` / `_post` | ✅ | `mdss_dsi_panel_off` |
| **`samsung_wait_after_reset_delay`** | ✅ | `mdss_dsi_panel_on`（第 21 轮补） |
| **`samsung_dsi_force_clock_lane_hs`** → `mdss_samsung_dsi_force_hs()` | ✅ | `mdss_dsi_panel_on`（第 21 轮补） |
| `samsung_timing_engine_control` | ⛔ 不做 | bak-2 里它只在 `if (vdd->support_hall_ic ...)` 分支内 —— **C7 没有霍尔/翻盖硬件**，该分支永不进入 |
| 文件作用域 `ss_dsi_panel_common` | ⛔ 不需要 | 框架符号通过正常链接解析（框架对象与核心在同一个 built-in.o） |

**22 处挂钩的处置到此为止**：需要做的全做了，剩下两处经核对属于"C7 硬件上不会走到"或"不需要"。

> 第 21 轮补的两处依赖已核对存在于 bak-2 框架头里：
> `reset_time_64`（字段）、`mdss_samsung_dsi_force_hs`（函数）、
> `samsung_wait_after_reset_delay` / `samsung_dsi_force_clock_lane_hs`（字段）。
