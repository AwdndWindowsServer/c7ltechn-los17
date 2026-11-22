#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deps-audit.py — 分析镜像里所有 ELF 的动态依赖，找出"库里缺失的 .so"。

为什么需要它：本移植把 2018 年（Android 8.0）的三星私有 blob 叠在 Android 15 的
vendor 上。如果某个三星库依赖的同名库被 donor 的 Android 15 版本顶掉、或者根本没被
带进来，这个 blob 在设备上就会 dlopen 失败 —— 这是"能开机但某个 HAL 永远起不来"的
最常见原因。静态查出来比在真机上翻 logcat 快得多。

用法: sudo python3 tools/deps-audit.py [system.img]
"""
import os, re, subprocess, sys, tempfile
from collections import defaultdict

LIB_DIRS = ["system/vendor/lib64", "system/vendor/lib", "system/lib64", "system/lib",
            "system/vendor/odm/lib64", "system/vendor/odm/lib"]
SEARCH_PREFIX = ["/apex", "/system", "/vendor", "/odm", "/system_ext", "/product"]

def needed(path):
    try:
        out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return []
    return re.findall(r"\(NEEDED\)\s+Shared library:\s+\[([^\]]+)\]", out)

def main():
    img = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "work", "build", "system.img"))
    mnt = tempfile.mkdtemp(prefix="c7deps.")
    subprocess.run(["mount", "-o", "loop,ro", img, mnt], check=True)
    try:
        # 建立"镜像内可解析的库名"集合：库目录里的文件名 + linker 的替代名
        have = set()
        for d in LIB_DIRS:
            p = os.path.join(mnt, d)
            if os.path.isdir(p):
                have |= set(os.listdir(p))
        # 常见 soname 变体（如 libfoo.so -> libfoo.so.1）
        scan = 0
        missing = defaultdict(list)
        for d in ("system/vendor/lib64", "system/vendor/lib"):
            p = os.path.join(mnt, d)
            if not os.path.isdir(p):
                continue
            for name in sorted(os.listdir(p)):
                fp = os.path.join(p, name)
                if not os.path.isfile(fp) or os.path.islink(fp):
                    continue
                with open(fp, "rb") as f:
                    if f.read(4) != b"\x7fELF":
                        continue
                scan += 1
                for dep in needed(fp):
                    if dep in have:
                        continue
                    # linker 也会去 /apex/*/lib64 找（运行时才挂载），这些不算缺
                    if dep.startswith(("libc.so", "libm.so", "libdl.so", "liblog.so",
                                       "libstdc++.so", "libandroid.so", "libz.so",
                                       "libbinder.so", "libutils.so", "libcutils.so",
                                       "libbase.so", "libhidlbase.so", "libhwbinder.so",
                                       "libhardware.so", "ld-android.so")):
                        continue
                    missing[dep].append(f"{d}/{name}")
        print("=" * 64)
        print(f" 动态依赖体检: 扫描 {scan} 个 vendor ELF，{len(have)} 个候选库名")
        print("=" * 64)
        if not missing:
            print("[OK] 所有 NEEDED 都能在镜像里找到")
        else:
            print(f"[WARN] {len(missing)} 个被依赖但镜像里没有的库（前 30，按依赖它的文件数排序）")
            for dep, users in sorted(missing.items(), key=lambda kv: -len(kv[1]))[:30]:
                print(f"  {dep}")
                for u in users[:3]:
                    print(f"        <- {u}")
                if len(users) > 3:
                    print(f"        ... 还有 {len(users)-3} 个")
            print()
            print("  说明：这些库要么需要从三星原厂 blob 里补（检查 AwdndWindowsServer/c7ltechn-vendor"
                  " 是否漏了），")
            print("        要么该 blob 本来就该被 donor 的 Android 15 实现替代（这时应从白名单里去掉它）。")
        print("=" * 64)
    finally:
        subprocess.run(["umount", mnt])
        os.rmdir(mnt)

if __name__ == "__main__":
    main()
