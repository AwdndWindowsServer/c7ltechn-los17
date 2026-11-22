#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit-image.py — 对组装好的 C7 system 镜像做"能不能开机"级别的静态体检。

检查项：
  1. 镜像尺寸 vs C7 SYSTEM 分区（3,774,873,600 B）
  2. /vendor 是否指向 /system/vendor
  3. SELinux 标签缺失的文件（从 git 拉来的 blob 最容易漏；漏了 HAL 直接被拒）
  4. 悬空符号链接（用"镜像内解析器"判断，绝对路径链接不会误报）
  5. vintf manifest 声明的 HAL 是否有对应实现线索（HIDL impl 库 / 服务名 / init rc）
  6. 两级 fstab 里是否还残留 /vendor 挂载行
  7. 关键三星文件清单

用法: sudo python3 tools/audit-image.py [system.img]
"""
import os, subprocess, sys, tempfile, xml.etree.ElementTree as ET

PART_SYSTEM_SIZE = 3774873600
# 运行时才存在/挂载的路径前缀（不参与悬空判断）
RUNTIME_PREFIX = ("/apex", "/data", "/storage", "/sys", "/proc", "/dev", "/mnt",
                  "/metadata", "/cache", "/tmp", "/firmware", "/dsp",
                  "/vendor/dsp", "/vendor/firmware_mnt", "/mnt/vendor/persist",
                  "/vendor/firmware", "/config", "/persist", "/efs", "/sdcard",
                  "/bugreports", "/odm", "/vendor_dlkm", "/odm_dlkm", "/system_dlkm")
# 已知"一个服务二进制提供多个 HAL"的情况（避免误报无实现）
COMBINED = {
    "android.hardware.audio": "audio.service",
    "android.hardware.audio.effect": "audio.service",
    "android.hardware.soundtrigger": "audio.service",
    "android.hardware.bluetooth.audio": "audio.service",
    "android.hardware.radio": "qcrild",
    "android.hardware.radio.config": "qcrild",
    "android.hardware.radio.deprecated": "rild",
    "android.hardware.secure_element": "qcrild",
    "android.hardware.graphics.mapper": "allocator",
    "android.hardware.graphics.allocator": "allocator",
    "android.hardware.tetheroffload.config": "ipacm",
    "android.hardware.tetheroffload.control": "ipacm",
    "android.hardware.wifi.supplicant": "wpa_supplicant",
    "android.hardware.wifi.hostapd": "hostapd",
    "android.hardware.gnss": "gnss",
    "android.hardware.health": "health",
    "android.hardware.power": "power",
    "android.hardware.memtrack": "memtrack",
}
KEY_C7_FILES = [
    "bin/hw/rild", "lib64/libsec-ril.so", "lib64/libsec-ril-dsds.so",
    "lib64/hw/fingerprint.default.so", "lib64/hw/sensors.msm8953.so",
    "bin/mm-qcamera-daemon", "lib64/hw/vendor.samsung.hardware.camera.provider@2.4-impl.so",
    "etc/camera/msm8953_camera.xml", "etc/mixer_paths.xml", "etc/Tfa9897.cnt",
    "etc/audio_platform_info.xml", "etc/gps.conf",
    "firmware/wlan/prima/WCNSS_qcom_wlan_nv.bin",
    "lib/libmm-qcamera.so", "lib64/camera.device@3.2-impl.so",
]

def resolve_in_image(mnt, abspath, guard=60):
    """在镜像内部模拟内核路径解析（绝对符号链接不会逃到宿主根）。"""
    parts = [p for p in abspath.split("/") if p]
    cur_rel = ""
    steps = 0
    while parts:
        steps += 1
        if steps > guard:
            return False
        nxt_rel = os.path.join(cur_rel, parts[0])
        full = os.path.join(mnt, nxt_rel)
        if os.path.islink(full):
            t = os.readlink(full)
            if t.startswith("/"):
                cur_rel = ""
                parts = [p for p in t.split("/") if p] + parts[1:]
            else:
                parts = [p for p in t.split("/") if p] + parts[1:]
            continue
        if os.path.exists(full):
            cur_rel = nxt_rel
            parts = parts[1:]
            continue
        return False
    return os.path.exists(os.path.join(mnt, cur_rel))

def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                           os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "work", "build", "system.img"))
    if not os.path.exists(root):
        sys.exit(f"找不到镜像: {root}")
    mnt = tempfile.mkdtemp(prefix="c7audit.")
    subprocess.run(["mount", "-o", "loop,ro", root, mnt], check=True)
    hard_fail = 0
    try:
        size = os.path.getsize(root)
        print("=" * 64)
        print(f" C7ROM 镜像体检  {root}")
        print(f" 大小 {size:,} 字节 ({size/2**30:.2f} GiB)")
        print("=" * 64)

        if size <= PART_SYSTEM_SIZE:
            print(f"[OK]   放得下 C7 SYSTEM 分区（余 {(PART_SYSTEM_SIZE-size)/2**20:.1f} MiB）")
        else:
            print("[FAIL] 镜像比分区大"); hard_fail += 1

        v = os.path.join(mnt, "vendor")
        if os.path.islink(v) and os.readlink(v) == "/system/vendor":
            print("[OK]   /vendor -> /system/vendor")
        else:
            print("[FAIL] /vendor 不是指向 /system/vendor 的符号链接"); hard_fail += 1

        unlabeled, dangling, n = [], [], 0
        for dirpath, dirnames, filenames in os.walk(mnt, followlinks=False):
            extra = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
            for name in filenames + extra:
                p = os.path.join(dirpath, name)
                if not os.path.lexists(p):
                    continue
                n += 1
                rel = p[len(mnt):]
                if os.path.islink(p):
                    t = os.readlink(p)
                    tgt_abs = t if t.startswith("/") else os.path.join(os.path.dirname(rel), t)
                    tgt_abs = os.path.normpath(tgt_abs)
                    if tgt_abs.startswith(RUNTIME_PREFIX):
                        continue
                    if not resolve_in_image(mnt, tgt_abs):
                        dangling.append(f"{rel} -> {t}")
                    continue
                try:
                    os.getxattr(p, "security.selinux", follow_symlinks=False)
                except OSError:
                    unlabeled.append(rel)

        print(f"--- 遍历 {n} 个文件/链接")
        print("[OK]   所有文件都有 security.selinux 标签" if not unlabeled else
              f"[WARN] {len(unlabeled)} 个文件缺 SELinux 标签（前 10）")
        for x in unlabeled[:10]:
            print("        " + x)
        # 区分"镜像内真悬空"和"运行时才存在"
        real = [d for d in dangling]
        if not real:
            print("[OK]   没有镜像内真悬空链接（运行时挂载点已排除）")
        else:
            print(f"[WARN] {len(real)} 个镜像内悬空链接（前 10，通常无害，但值得看一眼）")
            for x in real[:10]:
                print("        " + x)

        mnf = os.path.join(mnt, "system/vendor/etc/vintf/manifest.xml")
        print(f"--- vintf manifest: {'有' if os.path.exists(mnf) else '没有!'}")
        if os.path.exists(mnf):
            bins, impls = set(), set()
            for d in ("system/vendor/bin/hw", "system/vendor/bin"):
                pd = os.path.join(mnt, d)
                if os.path.isdir(pd):
                    bins |= set(os.listdir(pd))
            for d in ("system/vendor/lib64/hw", "system/vendor/lib/hw", "system/vendor/lib64", "system/vendor/lib"):
                pd = os.path.join(mnt, d)
                if os.path.isdir(pd):
                    impls |= set(os.listdir(pd))
            pdir = os.path.join(mnt, "system/vendor/etc/init")
            rcs = " ".join(os.listdir(pdir)) if os.path.isdir(pdir) else ""
            frag = ""
            fdir = os.path.join(mnt, "system/vendor/etc/vintf/manifest")
            if os.path.isdir(fdir):
                frag = " ".join(os.listdir(fdir))
            r = ET.parse(mnf).getroot()
            hals = [(h.findtext("name") or "", h.findtext("version") or "",
                     h.findtext("interface/name") or "") for h in r]
            unknown = []
            for name, ver, itf in hals:
                base = name
                short = ".".join(name.split(".")[-2:])
                hint = COMBINED.get(name, "")
                ok = False
                for b in bins:
                    if short in b or base in b or (hint and hint in b):
                        ok = True; break
                if not ok:
                    for lib in impls:
                        if base in lib or f"{base}@{ver}" in lib or short in lib:
                            ok = True; break
                if not ok and (short in rcs or short in frag):
                    ok = True
                if not ok:
                    unknown.append((name, ver, itf))
            print(f"  manifest {len(hals)} 个 HAL；{len(hals)-len(unknown)} 个能找到实现线索"
                  f"（服务名/impl 库/init rc/vintf fragment）")
            if unknown:
                print(f"  剩下 {len(unknown)} 个没找到线索（Android HAL 常由同一服务提供，"
                      f"真伪需真机 logcat 确认）：")
                for name, ver, itf in unknown[:10]:
                    print(f"        {name}@{ver} {itf}")
        else:
            hard_fail += 1

        f = os.path.join(mnt, "system/vendor/etc/fstab.qcom")
        if os.path.exists(f):
            bad = [l.strip() for l in open(f, errors="replace")
                   if l.strip() and not l.strip().startswith("#")
                   and len(l.split()) > 1 and l.split()[1] == "/vendor"]
            print(f"[{'OK' if not bad else 'FAIL'}]   vendor fstab 里的 /vendor 挂载行: {len(bad)}")
            for l in bad:
                print("        " + l)
            if bad:
                hard_fail += 1

        print("--- 关键三星文件")
        miss = 0
        for rel in KEY_C7_FILES:
            pv = os.path.join(mnt, "system/vendor", rel)
            ps = os.path.join(mnt, "system", rel)
            if not (os.path.lexists(pv) or os.path.lexists(ps)):
                print(f"        [缺失] {rel}"); miss += 1
        print(f"        {len(KEY_C7_FILES)-miss}/{len(KEY_C7_FILES)} 个关键文件在位"
              f"（vendor 或 system 侧任一处存在即算）")

        print("=" * 64)
        print(f" 结论: 硬性问题 {hard_fail} 项")
        print("=" * 64)
    finally:
        subprocess.run(["umount", mnt])
        os.rmdir(mnt)

if __name__ == "__main__":
    main()
