#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mkboot.py — 打三星 aboot 认的 Android boot 镜像（header v0 + dt(QCDT) 区）

  python3 mkboot.py --kernel Image.gz-dtb --ramdisk ramdisk.cpio.gz --dt dt.img \
                    --cmdline "..." --out boot.img [--os-version 10]

布局（与 mkbootimg + 三星 dt 区一致）：
  [page 2048] header | kernel (页对齐) | ramdisk (页对齐) | dt (页对齐) | SEANDROIDENFORCE
header 字段偏移：kernel_size=8 kernel_addr=12 ramdisk_size=16 ramdisk_addr=20
                 second_size=24 second_addr=28 tags_addr=32 page_size=36 dt_size=40
                 name=48(16B) cmdline=64(512B) id=576(32B)
"""
import argparse, struct, sys

PAGE = 2048


def align(n, p=PAGE):
    return (n + p - 1) // p * p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--ramdisk", required=True)
    ap.add_argument("--dt", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cmdline", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--page", type=int, default=PAGE)
    ap.add_argument("--base", type=lambda s: int(s, 0), default=0x80000000)
    ap.add_argument("--kernel-offset", type=lambda s: int(s, 0), default=0x8000)
    ap.add_argument("--ramdisk-offset", type=lambda s: int(s, 0), default=0x01000000)
    ap.add_argument("--tags-offset", type=lambda s: int(s, 0), default=0x100)
    ap.add_argument("--second-offset", type=lambda s: int(s, 0), default=0x00f00000)
    ap.add_argument("--os-version", type=int, default=10, help="Android 主版本（写 os_version 域）")
    ap.add_argument("--os-patch", type=int, default=2020, help="补丁年份，用于 os_version 低位")
    ap.add_argument("--no-seandroid", action="store_true", help="不追加 SEANDROIDENFORCE")
    a = ap.parse_args()

    kernel = open(a.kernel, "rb").read()
    ramdisk = open(a.ramdisk, "rb").read()
    dt = open(a.dt, "rb").read() if a.dt else b""

    p = a.page
    os_ver = ((a.os_version & 0x7f) << 25) | ((0 & 0x7f) << 18) | ((0 & 0x7f) << 11) \
             | (((a.os_patch - 2000) & 0x7f) << 4) | 5

    hdr = bytearray(p)
    hdr[0:8] = b"ANDROID!"
    struct.pack_into("<I", hdr, 8, len(kernel))
    struct.pack_into("<I", hdr, 12, a.base + a.kernel_offset)
    struct.pack_into("<I", hdr, 16, len(ramdisk))
    struct.pack_into("<I", hdr, 20, a.base + a.ramdisk_offset)
    struct.pack_into("<I", hdr, 24, 0)
    struct.pack_into("<I", hdr, 28, a.base + a.second_offset)
    struct.pack_into("<I", hdr, 32, a.base + a.tags_offset)
    struct.pack_into("<I", hdr, 36, p)
    struct.pack_into("<I", hdr, 40, len(dt))
    hdr[48:64] = a.name.encode()[:16].ljust(16, b"\0")
    hdr[64:576] = a.cmdline.encode()[:511].ljust(512, b"\0")

    out = bytearray(hdr)
    out += kernel.ljust(align(len(kernel), p), b"\0")
    out += ramdisk.ljust(align(len(ramdisk), p), b"\0")
    if dt:
        out += dt.ljust(align(len(dt), p), b"\0")
    if not a.no_seandroid:
        out += b"SEANDROIDENFORCE"

    open(a.out, "wb").write(out)
    print(f"boot.img -> {a.out}")
    print(f"  page={p} kernel={len(kernel)}(0x{a.base + a.kernel_offset:x}) "
          f"ramdisk={len(ramdisk)}(0x{a.base + a.ramdisk_offset:x}) dt={len(dt)} "
          f"total={len(out)}")
    print(f"  cmdline: {a.cmdline}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
