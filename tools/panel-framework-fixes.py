#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel-framework-fixes.py — 把三星面板框架适配到 4.9 mdss 的接口修补（幂等）

由 tools/panel-framework-setup.sh 调用，也可单独运行：
    python3 tools/panel-framework-fixes.py <内核树路径>

每一处修补都对应一个真实的编译错误（3.18 → 4.9 的接口差异），
说明写在代码注释里，便于以后核对。
"""
import os
import re
import sys

K = sys.argv[1] if len(sys.argv) > 1 else "work/kernel-4.9"
MSM = "drivers/video/fbdev/msm"
SAMSUNG = MSM + "/samsung"


def edit(path, fn):
    p = os.path.join(K, path)
    if not os.path.exists(p):
        print(f"    (跳过不存在的 {path})")
        return
    s = open(p, encoding="utf-8", errors="replace").read()
    n = fn(s)
    if n != s:
        open(p, "w", encoding="utf-8").write(n)
        print(f"    改: {path}")


# ---------------------------------------------------------------- 框架侧
def f_sync(s):
    """4.9 移除了老的 Android sync 框架；用到 sync 的调试代码本来是 #if 0"""
    if "#include <linux/sync.h>" not in s:
        return s
    s = s.replace("#include <linux/sync.h>\n",
                  "/* C7ROM: 4.9 已移除老的 Android sync 框架；本文件里用到 sync 的代码本来就是 #if 0 */\n")
    return s.replace("#include <linux/sw_sync.h>\n", "")


def f_debugfs_bool(s):
    """4.9 起 debugfs_create_bool 第 4 个参数是 bool*（3.18 是 u32*），字段本来就是 bool"""
    return (s.replace("(u32 *)&debug_data->print_cmds", "(bool *)&debug_data->print_cmds")
             .replace("(u32 *)&debug_data->panic_on_pptimeout", "(bool *)&debug_data->panic_on_pptimeout")
             .replace("(u32 *)debug_data->is_factory_mode", "(bool *)debug_data->is_factory_mode"))


def f_regulator(s):
    """4.9 的 of_get_regulator_init_data 多了第三个参数 (const struct regulator_desc *)"""
    n = [0]

    def rep(m):
        a = m.group(1)
        if a.count(",") >= 2:
            return m.group(0)
        n[0] += 1
        return f"of_get_regulator_init_data({a}, NULL)"

    return re.sub(r"of_get_regulator_init_data\(([^;]*?)\)", rep, s)


edit(SAMSUNG + "/ss_dsi_panel_common.h", f_sync)
for _f in ("ss_dsi_panel_debug.c", "ss_dsi_panel_common.c"):
    edit(SAMSUNG + "/" + _f, f_debugfs_bool)
edit(SAMSUNG + "/ss_regulator_common.c", f_regulator)


# ------------------------------------------------- 三星给核心结构体/枚举加的东西
def f_cmds(s):
    """struct dsi_panel_cmds: 三星加了 read_size/read_startoffset/name"""
    if "read_startoffset" in s:
        return s
    m = re.search(r"struct dsi_panel_cmds \{(.*?)\n\};", s, re.S)
    if not m:
        return s
    add = ("\n#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n"
           "\tchar *read_size;\n\tchar *read_startoffset;\n\tchar *name;\n#endif\n")
    return s[:m.end(1)] + add + s[m.end(1):]


def f_ctrl(s):
    """struct mdss_dsi_ctrl_pdata: 三星加了 event_handler 回调"""
    if "event_handler" in s:
        return s
    m = re.search(r"struct mdss_dsi_ctrl_pdata \{(.*?)\n\};", s, re.S)
    if not m:
        return s
    add = ("\n#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n"
           "\tint (*event_handler)(struct mdss_panel_data *pdata, int event, void *arg);\n#endif\n")
    return s[:m.end(1)] + add + s[m.end(1):]


def f_esd(s):
    """DSI ESD 寄存器枚举多了一个 ESD_REG_IRQ"""
    if "ESD_REG_IRQ," in s:
        return s
    return s.replace("\tESD_REG_NT35596,\n",
                     "\tESD_REG_NT35596,\n#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n\tESD_REG_IRQ,\n#endif\n", 1)


def f_decls(s):
    """三星新增的两个对外函数声明（实现在三星的 mdss 核心里，属于下一阶段）"""
    if "mdss_samsung_panel_cmd_read" in s:
        return s
    add = ("\n#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n"
           "int mdss_samsung_parse_dcs_cmds(struct device_node *np,\n"
           "\t\tstruct dsi_panel_cmds *pcmds, char *cmd_key, char *link_key);\n"
           "u32 mdss_samsung_panel_cmd_read(struct mdss_dsi_ctrl_pdata *ctrl,\n"
           "\t\tstruct dsi_panel_cmds *pcmds, int read_size);\n#endif\n")
    marker = "struct mdss_dsi_ctrl_pdata *mdss_dsi_get_ctrl(u32 ctrl_id);"
    return s.replace(marker, marker + add, 1) if marker in s else s + add


edit(MSM + "/mdss_dsi.h", f_cmds)
edit(MSM + "/mdss_dsi.h", f_ctrl)
edit(MSM + "/mdss_dsi.h", f_esd)
edit(MSM + "/mdss_dsi.h", f_decls)


def f_panel_data(s):
    """struct mdss_panel_data: 三星加了 panel_private"""
    if "panel_private" in s:
        return s
    m = re.search(r"struct mdss_panel_data \{(.*?)\n\};", s, re.S)
    if not m:
        return s
    add = "\n#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n\tvoid *panel_private;\n#endif\n"
    return s[:m.end(1)] + add + s[m.end(1):]


def f_panel_state(s):
    """struct mdss_panel_info: 三星加了 panel_state（blank_state 4.9 本来就有，别重复加）"""
    if "int panel_state;" in s:
        return s
    m = re.search(r"struct mdss_panel_info \{(.*?)\n\};", s, re.S)
    if not m:
        return s
    add = "\n#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n\tint panel_state;\n"
    if "blank_state;" not in s:
        add += "\tint blank_state;\n"
    add += "#endif\n"
    return s[:m.end(1)] + add + s[m.end(1):]


def f_events(s):
    """三星新增的 mdss 事件类型"""
    if "MDSS_SAMSUNG_EVENT_START" in s:
        return s
    add = ("#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n"
           "\tMDSS_SAMSUNG_EVENT_START,\n\tMDSS_SAMSUNG_EVENT_FRAME_UPDATE,\n"
           "\tMDSS_SAMSUNG_EVENT_FB_EVENT_CALLBACK,\n\tMDSS_SAMSUNG_EVENT_PANEL_ESD_RECOVERY,\n"
           "\tMDSS_SAMSUNG_EVENT_MULTI_RESOLUTION,\n\tMDSS_SAMSUNG_EVENT_MAX,\n#endif\n")
    return s.replace("\tMDSS_EVENT_UPDATE_PARAMS,\n", "\tMDSS_EVENT_UPDATE_PARAMS,\n" + add, 1)


edit(MSM + "/mdss_panel.h", f_panel_data)
edit(MSM + "/mdss_panel.h", f_panel_state)
edit(MSM + "/mdss_panel.h", f_events)


def f_debug_log(s):
    """三星在 mdss_debug.h 里加的 struct debug_log + debug_data.logd 成员"""
    if "struct debug_log {" not in s:
        add = ("\n#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\nstruct debug_log {\n\tstruct dentry *xlog;\n"
               "\tu32 xlog_enable;\n\tu32 panic_on_err;\n\tu32 enable_reg_dump;\n};\n#endif\n")
        s = s.replace("struct mdss_debug_data {", add + "\nstruct mdss_debug_data {", 1)
    if "logd;" not in s:
        m = re.search(r"struct mdss_debug_data \{(.*?)\n\};", s, re.S)
        if m:
            s = (s[:m.end(1)] + "\n#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n\tstruct debug_log logd;\n#endif\n"
                 + s[m.end(1):])
    return s


edit(MSM + "/mdss_debug.h", f_debug_log)


def f_broadcast(s):
    """DSI 命令标志 CMD_REQ_BROADCAST"""
    if "CMD_REQ_BROADCAST" in s:
        return s
    return s.replace("#define CMD_REQ_HS_MODE 0x0020\n",
                     "#define CMD_REQ_HS_MODE 0x0020\n\n#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n"
                     "/* temp REQ to send packet broadcast */\n#define CMD_REQ_BROADCAST 0x0080\n#endif\n", 1)


edit(MSM + "/mdss_dsi_cmd.h", f_broadcast)

# ---------------------------------------------------------------- bak-2 追加修补
def f_relpath(s):
    """bak-2 的框架假设自己在 drivers/video/msm/mdss/samsung/，用 ../../mdss/xxx.h；
    4.9 里我们放在 drivers/video/fbdev/msm/samsung/，应改成 ../xxx.h"""
    return s.replace('#include "../../mdss/', '#include "../')


def f_force_acl(s):
    """面板驱动要用的 op；框架里没人调用它，按面板实现的真实签名声明即可"""
    if 'samsung_force_acl_on' in s:
        return s
    marker = "\tstruct dsi_panel_cmds * (*samsung_brightness_acl_on)(struct mdss_dsi_ctrl_pdata *ctrl, int *level_key);\n"
    add = (marker + "\t/* C7ROM: 面板驱动要用、框架未声明；框架里无人调用，按实现签名声明 */\n"
           "\tint (*samsung_force_acl_on)(struct mdss_dsi_ctrl_pdata *ctrl);\n")
    return s.replace(marker, add, 1)


import glob as _glob
for _f in _glob.glob(os.path.join(K, SAMSUNG, "*.c")) + _glob.glob(os.path.join(K, SAMSUNG, "*.h")) + \
          _glob.glob(os.path.join(K, SAMSUNG, "S6E3FA3_AMS598KH01", "*.[ch]")):
    _rel = os.path.relpath(_f, K)
    edit(_rel, f_relpath)
edit(SAMSUNG + "/ss_dsi_panel_common.h", f_force_acl)

print("    接口修补完成（幂等，可重复运行）")
