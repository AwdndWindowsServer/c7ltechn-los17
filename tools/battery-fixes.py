#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
battery-fixes.py — 把三星 3.18 的电池栈（sec_battery + SM5705）改到 Linux 4.9 的
power_supply 模型上。**幂等**，可重复运行。

  用法: python3 tools/battery-fixes.py [内核树路径]      # 默认 work/kernel-4.9

要解决的三个结构性差异（都是 3.18 → 4.9 的核心改动，不是笔误）：

  ① power_supply 核心：3.18 的 `struct power_supply` 自己持有
     name/type/properties/num_properties/get_property/set_property
     （三星在此基础上又加了 40 多个枚举值）；4.9 把它们挪进了
     `struct power_supply_desc`，核心自己 kzalloc psy，只收 desc + cfg。
       → 补枚举（追加，保住 4.9 原有数值）
       → 把三星头里的 `struct power_supply psy_X` 就地改成 desc 载体
         `struct power_supply_desc psy_X`，并加一个 `struct power_supply *psy_X_p`
         存放核心返回的 psy 指针。这样三星那几十行 `psy_X.xxx = ...` 一行都不用动。

  ② 注册：3.18 是 `power_supply_register(dev, psy)` 两参数；4.9 是三参数
     （dev, desc, cfg），且 cfg 才是 drv_data / supplied_to 的来源。
       → 每个注册点展开成带 cfg 的块；drv_data 即容器指针。

  ③ 回调取上下文：3.18 用 `container_of(psy, struct sec_battery_info, psy_bat)`
     —— 4.9 的 psy 是核心分配的，container_of 必然错。
       → 全部换成 `power_supply_get_drvdata(psy)`（这正是 4.9 加 drv_data 的原因）。

  另外 `psy_do_property` 宏里 `psy->get_property/set_property` 是**宏**，
  展开在 100 多处调用点，所以那 200 多个报错其实只有 2 行源码要改。
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "work", "kernel-4.9")

PSY_HDR = os.path.join(K, "include/linux/power_supply.h")
BAT_DIR = os.path.join(K, "drivers/battery")
BAT_HDR = os.path.join(K, "include/linux/battery")

MARK = "C7ROM: 三星 power_supply 扩展"

# 三星 3.18 有、4.9 没有的枚举值（全部来自编译器报错清单，不是猜的）
PROPS = [
    "POWER_SUPPLY_PROP_CURRENT_FULL",
    "POWER_SUPPLY_PROP_MULTI_CHARGER_MODE",
    "POWER_SUPPLY_PROP_READ_SLAVE_REG",
    "POWER_SUPPLY_PROP_CHARGE_OTG_CONTROL",
    "POWER_SUPPLY_PROP_CHARGE_UNO_CONTROL",
    "POWER_SUPPLY_PROP_USB_CONFIGURE",
]
TYPES = [
    "POWER_SUPPLY_TYPE_MISC",
    "POWER_SUPPLY_TYPE_OTG",
    "POWER_SUPPLY_TYPE_CARDOCK",
    "POWER_SUPPLY_TYPE_UARTOFF",
    "POWER_SUPPLY_TYPE_LAN_HUB",
    "POWER_SUPPLY_TYPE_MHL_500",
    "POWER_SUPPLY_TYPE_MHL_900",
    "POWER_SUPPLY_TYPE_MHL_1500",
    "POWER_SUPPLY_TYPE_MHL_2000",
    "POWER_SUPPLY_TYPE_MHL_USB",
    "POWER_SUPPLY_TYPE_MHL_USB_100",
    "POWER_SUPPLY_TYPE_SMART_OTG",
    "POWER_SUPPLY_TYPE_SMART_NOTG",
    "POWER_SUPPLY_TYPE_POWER_SHARING",
    "POWER_SUPPLY_TYPE_HV_MAINS",
    "POWER_SUPPLY_TYPE_HV_PREPARE_MAINS",
    "POWER_SUPPLY_TYPE_HV_ERR",
    "POWER_SUPPLY_TYPE_HV_UNKNOWN",
    "POWER_SUPPLY_TYPE_HV_WIRELESS",
    "POWER_SUPPLY_TYPE_HV_WIRELESS_ETX",
    "POWER_SUPPLY_TYPE_PMA_WIRELESS",
    "POWER_SUPPLY_TYPE_WIRELESS_PACK",
    "POWER_SUPPLY_TYPE_WIRELESS_PACK_TA",
    "POWER_SUPPLY_TYPE_WIRELESS_STAND",
    "POWER_SUPPLY_TYPE_WIRELESS_HV_STAND",
    "POWER_SUPPLY_TYPE_MDOCK_TA",
    "POWER_SUPPLY_TYPE_HMT_CONNECTED",
    "POWER_SUPPLY_TYPE_HMT_CHARGE",
    "POWER_SUPPLY_TYPE_TIMEOUT",
]
HEALTHS = ["POWER_SUPPLY_HEALTH_OVERHEATLIMIT", "POWER_SUPPLY_HEALTH_UNDERVOLTAGE"]

# 容器结构体 → (头文件, [psy 成员])
CONTAINERS = {
    "sec_battery.h": ["psy_bat", "psy_usb", "psy_ac", "psy_wireless", "psy_ps"],
    "charger/sm5705_charger.h": ["psy_chg", "psy_otg"],
    "fuelgauge/sm5705_fuelgauge.h": ["psy_fg"],
}


def report(msg):
    print("  " + msg)


def enum_block(txt, anchor):
    """返回包含 anchor 的那个 enum 块的 (start, end, body_start, body_end) 位置。"""
    for m in re.finditer(r"enum\s+\w*\s*\{", txt):
        # 从 { 之后找到配对的第一个 '}'（枚举体里不会有嵌套花括号）
        body_start = m.end()
        body_end = txt.find("}", body_start)
        if body_end < 0:
            continue
        if anchor in txt[body_start:body_end]:
            return m.start(), body_end, body_start, body_end
    return None


def add_enum_members(txt, anchor, lines, tail_marker=None):
    """在某个 enum 的最后一个成员后插入 lines（保持 `};` 在最后）。"""
    blk = enum_block(txt, anchor)
    if blk is None:
        raise SystemExit("找不到包含 %s 的 enum" % anchor)
    _, _, _, body_end = blk
    ins = "".join("\t%s,\n" % l for l in lines)
    if tail_marker:
        ins += "\t%s\n" % tail_marker
    return txt[:body_end] + ins + txt[body_end:]


def fix_power_supply_hdr():
    print("[1/6] include/linux/power_supply.h：补三星扩展枚举")
    txt = open(PSY_HDR).read()
    if MARK in txt:
        report("已经是补过的状态，跳过")
        return
    # 属性枚举：三星独有属性 + PROP_MAX + EXT_PROP_MAX（三星的 EXT_PROP_* 都在
    # sec_charging_common.h 里以 POWER_SUPPLY_PROP_MAX 为起点继续编号）
    txt = add_enum_members(txt, "POWER_SUPPLY_PROP_STATUS", PROPS,
                           "POWER_SUPPLY_PROP_MAX,\n\t/* %s：EXT_PROP 起点与三星一致 */\n\tPOWER_SUPPLY_EXT_PROP_MAX = POWER_SUPPLY_PROP_MAX + 256" % MARK)
    # 类型枚举
    txt = add_enum_members(txt, "POWER_SUPPLY_TYPE_UNKNOWN", TYPES,
                           "POWER_SUPPLY_TYPE_MAX")
    # 健康枚举（4.9 里是匿名 enum）
    txt = add_enum_members(txt, "POWER_SUPPLY_HEALTH_GOOD", HEALTHS,
                           "POWER_SUPPLY_HEALTH_MAX")
    open(PSY_HDR, "w").write(txt)
    report("追加 %d 个属性 / %d 个类型 / %d 个健康值" % (len(PROPS), len(TYPES), len(HEALTHS)))


def fix_psy_do_property():
    print("[2/6] sec_charging_common.h：psy_do_property 改用 4.9 访问器")
    p = os.path.join(BAT_HDR, "sec_charging_common.h")
    txt = open(p).read()
    old = "\t\tif (psy->function##_property != NULL) { \\\n" \
          "\t\t\tret = psy->function##_property(psy, (property), &(value)); \\\n"
    new = "\t\t/* C7ROM: 4.9 的 handler 在 psy->desc 里，统一走访问器 */ \\\n" \
          "\t\tret = power_supply_##function##_property(psy, (property), &(value)); \\\n"
    if new in txt:
        report("已改过，跳过")
        return
    if old not in txt:
        raise SystemExit("psy_do_property 宏形状与预期不符，请人工确认")
    # 少一层 if，对应的收尾括号也要去掉一个
    txt = txt.replace(old, new, 1)
    tail_old = "\t\t\t}\t\\\n\t\t}\t\\\n\t}\t\\\n}\n"
    tail_new = "\t\t}\t\\\n\t}\t\\\n}\n"
    if tail_old in txt:
        txt = txt.replace(tail_old, tail_new, 1)
    open(p, "w").write(txt)
    report("宏已改：psy->get/set_property → power_supply_get/set_property")


def fix_psy_members():
    print("[3/6] 三星结构体：psy 成员改成 desc 载体 + 存返回指针")
    n = 0
    for rel, psys in CONTAINERS.items():
        p = os.path.join(BAT_HDR, rel)
        txt = open(p).read()
        for psy in psys:
            m = re.search(r"\tstruct power_supply[ \t]+%s;\n" % psy, txt)
            if m:
                txt = txt[:m.start()] + "\tstruct power_supply_desc\t%s;\t/* C7ROM: 4.9 的 desc 载体 */\n" % psy \
                      + "\tstruct power_supply\t*%s_p;\t\t/* 核心分配的 psy，注册后填 */\n" % psy \
                      + txt[m.end():]
                n += 1
        open(p, "w").write(txt)
    report("改了 %d 个 psy 成员（已是 desc 的会跳过）" % n)


def fix_supplied_to():
    print("[4/6] sec_battery.c：supplied_to 从 psy 挪到注册时的 cfg")
    p = os.path.join(BAT_DIR, "sec_battery.c")
    txt = open(p).read()
    n = len(re.findall(r"^\t\w+->psy_\w+\.(supplied_to|num_supplicants) = .*$\n", txt, re.M))
    if n == 0:
        report("已经没有裸的 supplied_to 赋值，跳过")
        return
    txt = re.sub(r"^\t\w+->psy_\w+\.(supplied_to|num_supplicants) = .*$\n", "", txt, flags=re.M)
    open(p, "w").write(txt)
    report("删掉 %d 行裸赋值（改由 cfg 传入）" % n)


def fix_registration():
    print("[5/6] 注册点：两参数 → desc + cfg（含 drv_data）")
    plan = [
        ("sec_battery.c", r"\tret = power_supply_register\(&pdev->dev, &battery->(psy_\w+)\);\n",
         "battery", "&pdev->dev", "pdev->dev.of_node", True),
        ("sm5705_charger.c", r"\tret = power_supply_register\(&pdev->dev, &charger->(psy_\w+)\);\n",
         "charger", "&pdev->dev", "pdev->dev.of_node", False),
        ("sm5705_fuelgauge.c", r"\tret = power_supply_register\(&client->dev, &fuelgauge->(psy_\w+)\);\n",
         "fuelgauge", "&client->dev", "client->dev.of_node", False),
    ]
    total = 0
    for fname, pat, holder, dev, ofnode, with_supplied in plan:
        p = os.path.join(BAT_DIR, fname)
        txt = open(p).read()
        def repl(m):
            psy = m.group(1)
            body = ("\t{\n"
                    "\t\tstruct power_supply_config sec_psy_cfg = {0};\n"
                    "\t\tsec_psy_cfg.drv_data = %s;\n"
                    "\t\tsec_psy_cfg.of_node = %s;\n" % (holder, ofnode))
            if with_supplied:
                body += ("\t\tsec_psy_cfg.supplied_to = supply_list;\n"
                         "\t\tsec_psy_cfg.num_supplicants = ARRAY_SIZE(supply_list);\n")
            body += ("\t\t%s->%s_p = power_supply_register(%s, &%s->%s, &sec_psy_cfg);\n"
                     "\t\tret = IS_ERR(%s->%s_p) ? PTR_ERR(%s->%s_p) : 0;\n"
                     "\t}\n" % (holder, psy, dev, holder, psy, holder, psy, holder, psy))
            return body
        txt, k = re.subn(pat, repl, txt)
        total += k
        open(p, "w").write(txt)
    report("改了 %d 个注册点" % total)


def fix_uses():
    print("[6/6] 其余用法：container_of / changed / unregister / .dev / psy_fg->get_property")
    stats = {}
    for fname in ("sec_battery.c", "sm5705_charger.c", "sm5705_fuelgauge.c", "sec_step_charging.c"):
        p = os.path.join(BAT_DIR, fname)
        txt = open(p).read()
        c = 0
        # container_of(psy, struct X, psy_Y)  → power_supply_get_drvdata(psy)
        txt, k = re.subn(r"container_of\(psy,\s*struct \w+,\s*psy_\w+\)",
                         "power_supply_get_drvdata(psy)", txt)
        c += k
        # power_supply_changed(&X->psy_Y) → power_supply_changed(X->psy_Y_p)
        txt, k = re.subn(r"power_supply_changed\(&(\w+)->(psy_\w+)\)",
                         r"power_supply_changed(\1->\2_p)", txt)
        c += k
        # power_supply_unregister(&X->psy_Y) → power_supply_unregister(X->psy_Y_p)
        txt, k = re.subn(r"power_supply_unregister\(&(\w+)->(psy_\w+)\)",
                         r"power_supply_unregister(\1->\2_p)", txt)
        c += k
        # X->psy_Y.dev → X->psy_Y_p->dev
        txt, k = re.subn(r"(\w+)->(psy_\w+)\.dev\b", r"\1->\2_p->dev", txt)
        c += k
        # 从别的驱动拿到的 psy（核心分配的）用它的 desc 取 handler
        # 只改「变量->get_property」，不改「变量->desc->get_property」：
        # 负向后视 (?<!->) 表示这个标识符前面不能是 ->（即它必须是变量而不是成员）
        txt, k = re.subn(r"(?<!->)\b(\w+)->get_property != NULL",
                         r"\1->desc->get_property != NULL", txt)
        txt, k2 = re.subn(r"(?<!->)\b(\w+)->get_property\((\w+),",
                          r"\1->desc->get_property(\2,", txt)
        c += k + k2
        stats[fname] = c
        open(p, "w").write(txt)
    report("；".join("%s: %d 处" % (k, v) for k, v in stats.items() if v))


def fix_muic_header_include():
    """muic.h 里有电池代码无条件要用的 ATTACHED_DEV_* 枚举，但三星把它挂在
    CONFIG_MUIC_NOTIFIER 守卫里。这里把 muic.h 提出来无条件包含（notifier 的
    API 头仍按原样守卫）。"""
    p = os.path.join(BAT_HDR, "sec_battery.h")
    txt = open(p).read()
    old = "#if defined(CONFIG_MUIC_NOTIFIER)\n" \
          "#include <linux/muic/muic.h>\n"
    new = "/* C7ROM: muic.h 提供 ATTACHED_DEV_* 枚举/类型，电池侧无条件要用；\n" \
          " * muic_notifier.h 的 API 仍然只在 CONFIG_MUIC_NOTIFIER 下引。 */\n" \
          "#include <linux/muic/muic.h>\n" \
          "#if defined(CONFIG_MUIC_NOTIFIER)\n"
    if new in txt:
        return 0
    if old not in txt:
        raise SystemExit("sec_battery.h 里 muic.h 的包含形式与预期不符")
    open(p, "w").write(txt.replace(old, new, 1))
    return 1


def fix_sm5705_mfd_header():
    """sm5705.h 里那行相对包含指向三星的 battery_v2 布局，我们用的是 battery/。"""
    p = os.path.join(K, "include/linux/mfd/sm5705/sm5705.h")
    txt = open(p).read()
    old = '#include "../../../../drivers/battery_v2/include/sec_charging_common.h"'
    new = '#include <linux/battery/sec_charging_common.h>\t/* C7ROM: 三星原为 battery_v2 相对路径 */'
    if new in txt:
        return 0
    if old not in txt:
        raise SystemExit("sm5705.h 的 sec_charging_common.h 包含形式与预期不符")
    open(p, "w").write(txt.replace(old, new, 1))
    return 1


def fix_tail():
    print("[7/7] 收尾：重复的 desc->、attrs 传参、muic 头")
    # 7a. 6.2 节两条正则叠在一起会产生 desc->desc->
    n = 0
    for fname in ("sec_battery.c", "sm5705_charger.c", "sm5705_fuelgauge.c"):
        p = os.path.join(BAT_DIR, fname)
        txt = open(p).read()
        txt, k = re.subn(r"->desc->desc->", "->desc->", txt)
        # 7b. create_attrs() 收 struct device *，要取地址
        txt, k2 = re.subn(r"(create_attrs)\((\w+)->(psy_\w+)_p->dev\)", r"\1(&\2->\3_p->dev)", txt)
        n += k + k2
        open(p, "w").write(txt)
    k3 = fix_muic_header_include()
    report("修正 desc-> 重复 / attrs 传参：%d 处；muic 头：%s" % (n, "已提出来" if k3 else "无需改"))


def fix_sysfs_text_tables():
    """★ 安全相关：4.9 的 power_supply sysfs 用 TEXT[value.intval] 直接索引，
    没有边界检查。我们给枚举追加了三星独有的值（20 号以后），一旦被
    get_property 返回（例如 psy_ps 的 type = POWER_SHARING、电池的 health =
    OVERHEATLIMIT），读对应的 sysfs 节点就会越界。这里把文本表按追加顺序补齐。"""
    print("[8/9] power_supply_sysfs.c：补齐文本表（防越界索引）")
    p = os.path.join(K, "drivers/power/supply/power_supply_sysfs.c")
    txt = open(p).read()
    # 与 TYPES / HEALTHS 的追加顺序严格对应（charge_type 的 SLOW 追加在枚举末尾）
    type_texts = [
        "MISC", "OTG", "CARDOCK", "UARTOFF", "LAN_HUB", "MHL_500", "MHL_900",
        "MHL_1500", "MHL_2000", "MHL_USB", "MHL_USB_100", "SMART_OTG",
        "SMART_NOTG", "POWER_SHARING", "HV_MAINS", "HV_PREPARE_MAINS", "HV_ERR",
        "HV_UNKNOWN", "HV_WIRELESS", "HV_WIRELESS_ETX", "PMA_WIRELESS",
        "WIRELESS_PACK", "WIRELESS_PACK_TA", "WIRELESS_STAND",
        "WIRELESS_HV_STAND", "MDOCK_TA", "HMT_CONNECTED", "HMT_CHARGE", "TIMEOUT",
    ]
    health_texts = ["Overheat limit", "Undervoltage"]
    work = [
        ("static char *type_text[] = {", type_texts),
        ("static char *health_text[] = {", health_texts),
        ("static char *charge_type[] = {", ["Slow"]),
    ]
    done = []
    changed = False
    for head, extras in work:
        i = txt.find(head)
        if i < 0:
            raise SystemExit("找不到 %s" % head)
        end = txt.find("};", i)
        # ★ 原表最后一个元素后面一般**没有**逗号；不补逗号直接把新元素接上去，
        #   会变成字符串拼接（"TYPEC_DFP" "MISC" → "TYPEC_DFPMISC"），必须先补
        body = txt[i:end]
        first = '"%s",' % extras[0]
        pos = body.find(first)
        if pos >= 0:
            # 已经补过：确认追加块前面有逗号，否则是字符串拼接（修中间态）
            before = body[:pos].rstrip()
            if not before.endswith(","):
                at = i + len(before)
                txt = txt[:at] + "," + txt[at:]
                changed = True
                done.append("%s 补逗号" % head.split()[2])
            continue
        # 首次追加：原表最后一个元素后面一般没有逗号，必须先补，否则
        # "TYPEC_DFP" "MISC" 会被编译器拼成 "TYPEC_DFPMISC"
        stripped = body.rstrip()
        if not stripped.endswith(","):
            at = i + len(stripped)
            txt = txt[:at] + "," + txt[at:]
            end += 1
            changed = True
        ins = "".join('\t\t"%s",\n' % s for s in extras)
        txt = txt[:end] + ins + txt[end:]
        changed = True
        done.append("%s +%d" % (head.split()[2], len(extras)))
    if changed:
        open(p, "w").write(txt)
    report("；".join(done) if done else "已补齐，跳过")


def fix_charge_type_slow():
    """sm5705_charger.c 用了 POWER_SUPPLY_CHARGE_TYPE_SLOW（4.9 没有）。"""
    txt = open(PSY_HDR).read()
    if "POWER_SUPPLY_CHARGE_TYPE_SLOW" in txt:
        return 0
    txt = add_enum_members(txt, "POWER_SUPPLY_CHARGE_TYPE_FAST",
                           ["POWER_SUPPLY_CHARGE_TYPE_SLOW"])
    open(PSY_HDR, "w").write(txt)
    return 1


def fix_misc():
    print("[9/9] 收尾：charge_type 枚举 + 三星清理路径里的 pdata")
    k1 = fix_charge_type_slow()
    p = os.path.join(BAT_DIR, "sm5705_charger.c")
    txt = open(p).read()
    # 三星 3.18 的 err_power_supply_register 里用了没声明的 pdata（本该释放
    # _get_sm5705_charger_platform_data() 里 kzalloc 的那份），改走 charger->pdata
    txt, k2 = re.subn(r"kfree\(pdata->charger_data\);", "kfree(charger->pdata);", txt)
    # 兼容上一版脚本留下的中间态
    txt, k2b = re.subn(r"kfree\(charger->pdata->charger_data\);", "kfree(charger->pdata);", txt)
    k2 += k2b
    open(p, "w").write(txt)
    report("charge_type: %s；pdata: %d 处" % ("已追加" if k1 else "已存在", k2))


def main():
    if not os.path.isdir(K):
        raise SystemExit("找不到内核树: %s" % K)
    print("内核树: %s\n" % K)
    fix_power_supply_hdr()
    fix_psy_do_property()
    fix_psy_members()
    fix_supplied_to()
    fix_registration()
    fix_uses()
    fix_tail()
    fix_sm5705_mfd_header()
    fix_sysfs_text_tables()
    fix_misc()
    print("\n完成（幂等，可重复运行）")


if __name__ == "__main__":
    main()
