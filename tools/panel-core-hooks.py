#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel-core-hooks.py — 把「4.9 显示核心调用三星面板框架」的改动打进去（幂等）

由 tools/panel-framework-setup.sh 调用，也可单独运行：
    python3 tools/panel-core-hooks.py <内核树路径>

内容分三类：
  A. 核心侧实现：从三星 bak-2 移植的 2 个函数（mdss_dsi_panel.c 末尾）
  B. 核心侧导出：mdss_dsi_panel_cmds_send 去掉 static（框架要跨文件调用）
  C. 挂钩调用点：mdss_dsi_panel_reset / _on / _off 三处，让核心回头调用三星框架

每一步都对应一个真实编译错误或功能缺口，注释写在代码里。
"""
import os
import re
import sys

K = sys.argv[1] if len(sys.argv) > 1 else "work/kernel-4.9"
F = os.path.join(K, "drivers/video/fbdev/msm/mdss_dsi_panel.c")

CORE_FUNCS = '''
#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)
/* C7ROM: 从三星 bak-2 的 mdss_dsi_panel.c 移植（三星显示栈需要这两个函数） */
int mdss_samsung_parse_dcs_cmds(struct device_node *np,
		struct dsi_panel_cmds *pcmds, char *cmd_key, char *link_key)
{
	return mdss_dsi_parse_dcs_cmds(np, pcmds, cmd_key, link_key);
}

u32 mdss_samsung_panel_cmd_read(struct mdss_dsi_ctrl_pdata *ctrl,
		struct dsi_panel_cmds *pcmds, int read_size)
{
	struct dcs_cmd_req cmdreq;
	struct mdss_panel_info *pinfo;

	pinfo = &(ctrl->panel_data.panel_info);
	if (pinfo->dcs_cmd_by_left) {
		if (ctrl->ndx != DSI_CTRL_LEFT)
			return -EINVAL;
	}

	memset(&cmdreq, 0, sizeof(cmdreq));
	cmdreq.cmds = pcmds->cmds;
	cmdreq.cmds_cnt = 1;
	cmdreq.flags = CMD_REQ_RX | CMD_REQ_COMMIT;

	if (read_size)
		cmdreq.rlen = read_size;
	else
		cmdreq.rlen = pcmds->read_size[0];

	cmdreq.rbuf = ctrl->rx_buf.data;
	cmdreq.cb = NULL; /* call back */
	mdss_dsi_cmdlist_put(ctrl, &cmdreq);

	return ctrl->rx_buf.len;
}
#endif
'''

VDD_DECL = '''#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)
	/* C7ROM: 三星面板数据（挂钩） */
	struct samsung_display_driver_data *vdd = samsung_get_vdd();
#endif'''

VDD_DECL_ON = '''#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)
	/* C7ROM: 三星面板数据（挂钩） */
	struct samsung_display_driver_data *vdd = samsung_get_vdd();

	if (!vdd)
		pr_warn("%s: samsung panel data missing\\n", __func__);
#endif'''

RESET_ON_DELAY = '''
#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)
				/* C7ROM: 三星面板上电复位延时 */
				if (vdd && vdd->dtsi_data[ctrl_pdata->ndx].samsung_power_on_reset_delay)
					usleep_range(
						vdd->dtsi_data[ctrl_pdata->ndx].samsung_power_on_reset_delay,
						vdd->dtsi_data[ctrl_pdata->ndx].samsung_power_on_reset_delay);
#endif
'''

RESET_OFF_DELAY = '''
#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)
			/* C7ROM: 三星面板下电复位延时 */
			if (vdd && vdd->dtsi_data[ctrl_pdata->ndx].samsung_power_off_reset_delay)
				usleep_range(
					vdd->dtsi_data[ctrl_pdata->ndx].samsung_power_off_reset_delay,
					vdd->dtsi_data[ctrl_pdata->ndx].samsung_power_off_reset_delay);
			usleep_range(200, 200);
#endif
'''


# ---- C4. _on 里的复位等待与强制 HS（第 21 轮补上）----
WAIT_ON = """
#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)
	/* C7ROM: 三星面板"复位后等待"与"强制 HS 时钟"（来自 bak-2 mdss_dsi_panel_on） */
	if (vdd && vdd->dtsi_data[ctrl->ndx].samsung_wait_after_reset_delay) {
		reset_delay_32 = vdd->dtsi_data[ctrl->ndx].samsung_wait_after_reset_delay;
		reset_delay_64 = (s64)reset_delay_32;
		cur_time_64 = ktime_to_ms(ktime_get());
		wait_time_64 = reset_delay_64 - (cur_time_64 - vdd->reset_time_64);
		if (wait_time_64 <= 0)
			wait_time_32 = 0;
		else if (wait_time_64 > reset_delay_64)
			wait_time_32 = reset_delay_32;
		else
			wait_time_32 = (s32)wait_time_64;
		if (wait_time_32 > 0)
			usleep_range(wait_time_32 * 1000, wait_time_32 * 1000);
	}

	if (vdd && vdd->dtsi_data[ctrl->ndx].samsung_dsi_force_clock_lane_hs)
		mdss_samsung_dsi_force_hs(pdata);
#endif
"""

WAIT_LOCALS = """#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)
	u32 reset_delay_32 = 0;
	s64 reset_delay_64 = 0, cur_time_64 = 0, wait_time_64 = 0;
	s32 wait_time_32 = 0;
#endif"""


def add_on_wait(s):
    if "samsung_wait_after_reset_delay" in s:
        return s
    lines = s.split("\n")

    def find_func(name):
        for idx, l in enumerate(lines):
            if re.match(r"^(static\s+)?[\w \*]+\b" + name + r"\s*\(", l):
                return idx
        return -1

    i = find_func("mdss_dsi_panel_on")
    if i < 0:
        return s
    k = next(x for x in range(i, i + 400) if "mdss_samsung_panel_on_pre(pdata);" in lines[x])
    ind = re.match(r"\s*", lines[k]).group(0)
    lines.insert(k, ind + WAIT_ON.strip().replace("\n", "\n" + ind))
    # 局部变量加到函数开头（跟在 vdd 声明块之后）
    i = find_func("mdss_dsi_panel_on")
    j = next(x for x in range(i, i + 60) if "if (!vdd)" in lines[x])
    lines.insert(j + 2, WAIT_LOCALS)
    print("  C4. on 挂钩补齐（wait_after_reset_delay + force_clock_lane_hs）")
    return "\n".join(lines)

def main():
    s = open(F, encoding="utf-8", errors="replace").read()
    orig = s

    # ---- A. 移植的 2 个函数 ----
    if "mdss_samsung_panel_cmd_read" not in s:
        s = s.rstrip("\n") + "\n" + CORE_FUNCS
        print("  A. 追加 2 个三星核心函数")

    # ---- B. 导出 mdss_dsi_panel_cmds_send ----
    m = re.search(r"\nstatic\s+([\w \*]*mdss_dsi_panel_cmds_send\s*\([^)]*\)\s*\n?\{)", s)
    if m:
        s = (s[:m.start()] + "\n/* C7ROM: 三星框架要跨文件调用它，故去掉 static（与三星核心一致） */\n"
             + m.group(1) + s[m.end():])
        print("  B. mdss_dsi_panel_cmds_send 去掉 static")

    # ---- C1. include 三星框架头 ----
    if "samsung/ss_dsi_panel_common.h" not in s:
        anchor = '#include "mdss_dsi.h"'
        if anchor in s:
            s = s.replace(anchor, anchor + '\n#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n'
                                        '#include "samsung/ss_dsi_panel_common.h"\n#endif', 1)
            print("  C1. include 三星框架头")

    # ---- C2. reset 挂钩 ----
    if "samsung_power_on_reset_delay" not in s:
        anchor = ("\t\t\t\tgpio_set_value((ctrl_pdata->disp_en_gpio), 1);\n"
                  "\t\t\t\tusleep_range(100, 110);\n")
        if anchor in s:
            s = s.replace(anchor, anchor + RESET_ON_DELAY, 1)
            print("  C2a. reset 上电延时挂钩")
    if "samsung_power_off_reset_delay" not in s:
        i = s.find("int mdss_dsi_panel_reset(")
        seg = s[i:i + 12000]
        anchor = "gpio_set_value((ctrl_pdata->rst_gpio), 0);"
        k = seg.find(anchor)
        if k > 0:
            seg = seg[:k] + anchor + RESET_OFF_DELAY + seg[k + len(anchor):]
            s = s[:i] + seg + s[i + 12000:]
            print("  C2b. reset 下电延时挂钩")

    # vdd 声明（reset 函数）
    _reset_body = s.split("int mdss_dsi_panel_reset(", 1)[1][:1500] if "int mdss_dsi_panel_reset(" in s else ""
    if "samsung_power_on_reset_delay" in s and "samsung_get_vdd" not in _reset_body:
        i = s.find("int mdss_dsi_panel_reset(")
        j = s.find("pinfo = &(ctrl_pdata->panel_data.panel_info);\n", i)
        if j > 0:
            k = j + len("pinfo = &(ctrl_pdata->panel_data.panel_info);\n")
            s = s[:k] + "\n" + VDD_DECL + "\n" + s[k:]
            print("  C2c. reset 函数里加 vdd 声明")

    # ---- C3. on/off 挂钩（按行插入，找锚点） ----
    lines = s.split("\n")

    def find_func(name):
        for idx, l in enumerate(lines):
            if re.match(r"^(static\s+)?[\w \*]+\b" + name + r"\s*\(", l):
                return idx
        return -1

    if "mdss_samsung_panel_on_pre" not in s:
        i = find_func("mdss_dsi_panel_on")
        if i > 0:
            j = i
            while "{" not in lines[j]:
                j += 1
            lines.insert(j + 1, VDD_DECL_ON)
            i = find_func("mdss_dsi_panel_on")
            k = next(x for x in range(i, i + 400) if "mdss_dsi_panel_cmds_send(ctrl, on_cmds" in lines[x])
            ind = re.match(r"\s*", lines[k]).group(0)
            lines.insert(k, ind + "#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n" + ind +
                        "\t/* C7ROM: 面板初始化序列由三星框架发（挂钩） */\n" + ind +
                        "\tmdss_samsung_panel_on_pre(pdata);\n" + ind + "#endif")
            k = next(x for x in range(i, i + 400) if "mdss_dsi_panel_cmds_send(ctrl, on_cmds" in lines[x])
            lines.insert(k + 1, ind + "#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n" + ind +
                        "\tmdss_samsung_panel_on_post(pdata);\n" + ind +
                        "\tpinfo->panel_state = true;\n" + ind + "#endif")
            print("  C3a. on 挂钩（on_pre / on_post / panel_state）")

    if "mdss_samsung_panel_off_pre" not in s:
        i = find_func("mdss_dsi_panel_off")
        if i > 0:
            j = i
            while "{" not in lines[j]:
                j += 1
            lines.insert(j + 1, VDD_DECL)
            i = find_func("mdss_dsi_panel_off")
            k = next(x for x in range(i, i + 400) if "ctrl->off_cmds.cmd_cnt" in lines[x])
            ind = re.match(r"\s*", lines[k]).group(0)
            lines.insert(k, ind + "#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n" + ind +
                        "\t/* C7ROM: 关屏序列由三星框架走（挂钩） */\n" + ind +
                        "\tpinfo->blank_state = MDSS_PANEL_BLANK_BLANK;\n" + ind +
                        "\tmdss_samsung_panel_off_pre(pdata);\n" + ind + "#endif")
            k = next(x for x in range(i, i + 400) if "mdss_dsi_panel_cmds_send(ctrl, &ctrl->off_cmds" in lines[x])
            lines.insert(k + 1, ind + "#if defined(CONFIG_FB_MSM_MDSS_SAMSUNG)\n" + ind +
                        "\tmdss_samsung_panel_off_post(pdata);\n" + ind +
                        "\tpinfo->panel_state = false;\n" + ind + "#endif")
            print("  C3b. off 挂钩（blank_state / off_pre / off_post / panel_state）")

    s = add_on_wait("\n".join(lines))
    if s != orig:
        open(F, "w", encoding="utf-8").write(s)
    print("  完成（幂等，可重复运行）")


if __name__ == "__main__":
    main()
