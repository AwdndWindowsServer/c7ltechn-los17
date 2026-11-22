#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dts-pinctrl-318to49.py — 把三星 3.18 的 pinctrl dtsi 机械转换成 4.9 的写法。

背景（实测）：三星 3.18 的 pinctrl 文件是 gcdb 自动生成的，结构是

    &soc {
        tlmm: pinctrl@1000000 {
            tsp_int {                       ← 外层包装（旧式属性都在这层）
                qcom,num-grp-pins = <1>;
                qcom,pin-func = <0>;
                tsp_int_active: tsp_int_active {   ← 内层才是真正的 pin state
                    mux    { pins = "gpio59"; function = "gpio"; };
                    config { pins = "gpio59"; drive-strength = <2>; bias-disable; };
                };
            };
        };
    };

而 4.9 的写法是把**内层节点直接挂到 &tlmm 下面**（外层包装、qcom,num-grp-pins、
qcom,pin-func 全都不需要）。所以转换是纯机械的：把每个含 mux/config 直接子节点的
带 label 节点抠出来，外面套一个 `&tlmm { ... }` 即可。

用法:
  python3 tools/dts-pinctrl-318to49.py <3.18-pinctrl.dtsi> [输出.dtsi]
"""
import os, re, sys

def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    return s

NODE_RE = re.compile(r"^\s*(?:([A-Za-z0-9_\-]+)\s*:\s*)?([A-Za-z0-9_,@\-]+)\s*\{\s*$")
PROP_RE = re.compile(r"^\s*[A-Za-z0-9_,\-]+\s*=")

def render(fr, indent):
    pad = "\t" * indent
    head = f"{pad}{fr['label']}: {fr['name']} {{" if fr["label"] else f"{pad}{fr['name']} {{"
    lines = [head]
    for prop in fr["props"]:
        lines.append("\t" * (indent + 1) + prop)
    for kid in fr["kids"]:
        lines += render(kid, indent + 1)
    lines.append(f"{pad}}};")
    return lines

def convert(text):
    lines = strip_comments(text).splitlines()
    stack, leaves = [], []
    for ln in lines:
        s = ln.strip()
        if s == "":
            continue
        m = NODE_RE.match(ln)
        if m:
            stack.append({"name": m.group(2), "label": m.group(1),
                          "props": [], "kids": [], "children": []})
            continue
        if s.startswith("}"):
            if not stack:
                continue
            fr = stack.pop()
            if stack:
                stack[-1]["kids"].append(fr)
                stack[-1]["children"].append(fr["name"])
            if fr["label"] and ("mux" in fr["children"] or "config" in fr["children"]):
                leaves.append(fr)
            continue
        if stack:
            stack[-1]["props"].append(s)
    return leaves

def emit(leaves):
    out = ["/* 由 tools/dts-pinctrl-318to49.py 从三星 3.18 pinctrl dtsi 自动转换生成",
           " * 内层 pin state 原样搬过来，外层包装/qcom,num-grp-pins/qcom,pin-func 已去掉",
           " */",
           "",
           "&tlmm {"]
    for fr in leaves:
        fr = dict(fr, name=fr["label"] or fr["name"])   # 节点名 = label，避免 default/active 撞名
        out += render(fr, 1)
    out.append("};")
    return "\n".join(out) + "\n"

# ---------------------------------------------------------------- 冲突处理
LABEL_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*:", re.M)
GPIO_RE = re.compile(r'"gpio(\d+)"')

def collect_existing_labels(dirs):
    """扫描 4.9 树里已有的 dts/dtsi，收集所有已占用的 label。"""
    labels = set()
    for d in dirs:
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith((".dts", ".dtsi")):
                    try:
                        txt = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
                    except OSError:
                        continue
                    labels |= set(LABEL_RE.findall(txt))
    return labels

def gpios_of(leaf):
    out = set()
    for prop in leaf["props"]:
        out |= set(GPIO_RE.findall(prop))
    for kid in leaf["kids"]:
        out |= gpios_of(kid)
    return out

def existing_gpios(label, dirs):
    """在 4.9 树里找同名 label 的节点，抽出它用的 gpio（粗略但够用）。"""
    for d in dirs:
        for root, _, files in os.walk(d):
            for f in files:
                if not f.endswith((".dts", ".dtsi")):
                    continue
                txt = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
                m = re.search(rf"^\s*{re.escape(label)}\s*:", txt, re.M)
                if not m:
                    continue
                seg = txt[m.start(): m.start() + 800]
                return set(GPIO_RE.findall(seg))
    return None

# ------------------------------------------------- 基线比对（比 --skip-labels-file 更准）
def baseline_label_gpios(dts_path):
    """从 dtc 预处理后的基线 DTS 里抽出 {label: set(gpio)}。"""
    txt = open(dts_path, encoding="utf-8", errors="replace").read()
    lines = txt.splitlines()
    out = {}
    stack = []
    for ln in lines:
        m = NODE_RE.match(ln)
        if m:
            stack.append({"label": m.group(1), "gpios": set()})
            continue
        if ln.strip().startswith("}") and stack:
            fr = stack.pop()
            if fr["label"]:
                out.setdefault(fr["label"], set()).update(fr["gpios"])
            if stack:
                stack[-1]["gpios"] |= fr["gpios"]
            continue
        g = GPIO_RE.findall(ln)
        if g and stack:
            stack[-1]["gpios"].update(g)
    return out

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    skip_dirs = []
    if "--skip-labels-from" in sys.argv:
        skip_dirs = sys.argv[sys.argv.index("--skip-labels-from") + 1].split(",")
    src = args[0]
    dst = args[1] if len(args) > 1 else None
    leaves = convert(open(src, encoding="utf-8", errors="replace").read())

    skipped, conflicts, renamed = [], [], []
    have = set()
    base_gpios = None
    if "--baseline-dts" in sys.argv:
        base_gpios = baseline_label_gpios(sys.argv[sys.argv.index("--baseline-dts") + 1])
        have = set(base_gpios.keys())
        print(f"基线: {len(have)} 个 label（含引脚号，用于判重）")
    if "--skip-labels-file" in sys.argv:
        # 精准做法：用 dtc 预处理后的基线 DTS（.dts.tmp）里的 label 集合
        # 例：make qcom/msm8953-mtp.dtb 后取 .msm8953-mtp.dtb.dts.tmp
        lf = sys.argv[sys.argv.index("--skip-labels-file") + 1]
        have = set(l.strip() for l in open(lf, encoding="utf-8") if l.strip())
        print(f"基线 label 集合: {len(have)} 个（来自 {lf}）")
    elif skip_dirs:
        have = collect_existing_labels(skip_dirs)
    if have:
        keep = []
        prefix = ""
        if "--rename-prefix" in sys.argv:
            prefix = sys.argv[sys.argv.index("--rename-prefix") + 1]
        for fr in leaves:
            if fr["label"] in have:
                a = gpios_of(fr)
                b = base_gpios.get(fr["label"], set()) if base_gpios is not None else set()
                if a and b and a != b and prefix:
                    # 引脚号与基线不同 —— 这是 C7 真正自己的配置，不能丢！
                    # 改名（加前缀）后保留，避免 duplicate_label
                    new = dict(fr, label=prefix + fr["label"])
                    renamed.append((fr["label"], new["label"], sorted(a), sorted(b)))
                    keep.append(new)
                else:
                    skipped.append(fr["label"])
                    if a and b and a != b:
                        conflicts.append((fr["label"], sorted(a), sorted(b)))
            else:
                keep.append(fr)
        leaves = keep
        print(f"跳过 4.9 树里已存在的 label: {len(skipped)} 个 -> {', '.join(sorted(skipped)[:12])}"
              f"{' …' if len(skipped) > 12 else ''}")
        if renamed:
            print(f"[rename] {len(renamed)} 个 label 与基线**引脚号不同**，已改名保留（这是 C7 自己的配置，不能丢）:")
            for old, new, a, b in renamed[:12]:
                print(f"      {old} -> {new}   C7 gpio({','.join(a)}) vs 基线 gpio({','.join(b)})")
        if conflicts:
            print(f"[!] 其中 {len(conflicts)} 个 **引脚号与 4.9 现有定义不同**，需要人工决定用谁的:")
            for lab, a, b in conflicts[:15]:
                print(f"      {lab}: C7(gpio {','.join(a)})  vs  4.9(gpio {','.join(b)})")
    text = emit(leaves)
    if dst:
        open(dst, "w", encoding="utf-8").write(text)
        print(f"转换完成: {len(leaves)} 个 pin state -> {dst}")
    else:
        print(text)
    old = [l for l in text.splitlines() if "qcom," in l and "=" in l]
    if old:
        print(f"[warn] 输出里仍有 {len(old)} 行旧式 qcom, 属性（需要人工看一下）:")
        for l in old[:8]:
            print("   ", l.strip())

if __name__ == "__main__":
    main()
