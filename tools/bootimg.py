#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bootimg.py -- 自包含 Android boot/init_boot 镜像拆包与打包工具
支持 header v0 / v1 / v2（AOSP 及 Samsung 变体），ramdisk 支持 gzip / lz4 / xz / lzma / bzip2 / cpio(裸)。

  unpack <boot.img> <outdir>     # 拆包: header.json, kernel, ramdisk.cpio.gz(原始), ramdisk/, dtb, second
  repack <indir>  <out.img>      # 打包: 读 header.json + kernel + ramdisk(可自动压缩) [+ dtb] [+ second]
  info   <boot.img>              # 打印头部信息(不解包)
  rd-unpack <ramdisk> <outdir>   # 仅解 ramdisk
  rd-pack   <dir> <out.cpio[.gz]># 仅打 ramdisk

无外部依赖（除 lz4/xz 命令行用于对应压缩格式）。
"""
import json, os, shutil, struct, subprocess, sys, gzip, zlib, io

MAGIC = b"ANDROID!"
VENDOR_MAGIC = b"VNDRBOOT"

def r32(b, o):  return struct.unpack_from("<I", b, o)[0]

def decompress(data, comp):
    if comp == "gzip":   return gzip.decompress(data)
    if comp == "lz4":
        return subprocess.run(["lz4", "-d", "-c"], input=data, capture_output=True, check=True).stdout
    if comp in ("xz", "lzma"):
        return subprocess.run(["xz", "-d", "-c", "--format=lzma" if comp == "lzma" else "--format=xz"],
                              input=data, capture_output=True, check=True).stdout if comp == "lzma" else \
               subprocess.run(["xz", "-d", "-c"], input=data, capture_output=True, check=True).stdout
    if comp == "bzip2":  import bz2; return bz2.decompress(data)
    if comp == "lzma_alone":
        import lzma; return lzma.decompress(data, format=lzma.FORMAT_ALONE)
    if comp == "zstd":
        return subprocess.run(["zstd", "-d", "-c"], input=data, capture_output=True, check=True).stdout
    if comp == "cpio":   return data
    # 猜
    if data[:2] == b"\x1f\x8b": return gzip.decompress(data)
    if data[:4] == b"\x02\x21\x4c\x18": return decompress(data, "lz4")
    if data[:6] == b"\xfd7zXZ\x00": return decompress(data, "xz")
    if data[:3] == b"BZh": return decompress(data, "bzip2")
    if data[:4] == b"\x28\xb5\x2f\xfd": return decompress(data, "zstd")
    return data

def compress(data, comp):
    if comp == "gzip":
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as f: f.write(data)
        return buf.getvalue()
    if comp == "lz4":
        return subprocess.run(["lz4", "-l", "-9", "-c"], input=data, capture_output=True, check=True).stdout
    if comp == "xz":
        return subprocess.run(["xz", "-9", "-c"], input=data, capture_output=True, check=True).stdout
    return data

def detect_comp(data):
    if data[:2] == b"\x1f\x8b": return "gzip"
    if data[:4] == b"\x02\x21\x4c\x18": return "lz4"
    if data[:6] == b"\xfd7zXZ\x00": return "xz"
    if data[:3] == b"BZh": return "bzip2"
    if data[:4] == b"\x28\xb5\x2f\xfd": return "zstd"
    if data[:6] == b"070701" or data[:6] == b"070702": return "cpio"
    return "none"

def parse_header(b):
    if b[:8] != MAGIC:
        raise SystemExit("不是 Android boot 镜像（magic 不匹配）")
    h = {}
    h["magic"] = "ANDROID!"
    h["kernel_size"]      = r32(b, 8)
    h["kernel_addr"]      = r32(b, 12)
    h["ramdisk_size"]     = r32(b, 16)
    h["ramdisk_addr"]     = r32(b, 20)
    h["second_size"]      = r32(b, 24)
    h["second_addr"]      = r32(b, 28)
    h["tags_addr"]        = r32(b, 32)
    h["page_size"]        = r32(b, 36)
    h["header_version"]   = r32(b, 40)
    h["os_version"]       = r32(b, 44)
    h["name"]             = b[48:64].split(b"\x00")[0].decode("utf-8", "replace")
    h["cmdline"]          = b[64:576].split(b"\x00")[0].decode("utf-8", "replace")
    h["id"]               = b[576:608].hex()
    h["extra_cmdline"]    = b[608:1632].split(b"\x00")[0].decode("utf-8", "replace")
    if h["header_version"] >= 1:
        h["recovery_dtbo_size"]   = r32(b, 1632)
        h["recovery_dtbo_offset"] = struct.unpack_from("<Q", b, 1636)[0]
        h["header_size"]          = r32(b, 1644)
    if h["header_version"] >= 2:
        h["dtb_size"] = r32(b, 1648)
        h["dtb_addr"] = struct.unpack_from("<Q", b, 1652)[0]
    return h

def os_version_str(v):
    if not v: return "0.0.0"
    a = (v >> 25) & 0x7f; b = (v >> 18) & 0x7f; c = (v >> 11) & 0x7f
    y = 2000 + ((v >> 4) & 0x7f); m = v & 0xf
    return f"{a}.{b}.{c} (patch {y}-{m:02d})"

def align(n, page):
    return (n + page - 1) // page * page

def unpack(img, outdir):
    raw = open(img, "rb").read()
    h = parse_header(raw)
    p = h["page_size"]
    o = p  # header 占一页
    os.makedirs(outdir, exist_ok=True)
    def take(size):
        nonlocal o
        d = raw[o:o+size]; o = align(o + size, p); return d

    kernel = take(h["kernel_size"]);  open(f"{outdir}/kernel", "wb").write(kernel)
    ramdisk = take(h["ramdisk_size"]); open(f"{outdir}/ramdisk.orig", "wb").write(ramdisk)
    if h["second_size"]:
        open(f"{outdir}/second", "wb").write(take(h["second_size"]))
    if h.get("recovery_dtbo_size"):
        open(f"{outdir}/recovery_dtbo", "wb").write(take(h["recovery_dtbo_size"]))
    if h.get("dtb_size"):
        open(f"{outdir}/dtb", "wb").write(take(h["dtb_size"]))
    # kernel 里可能内嵌 dtb (Image.gz-dtb)：尝试分离
    h["ramdisk_compression"] = detect_comp(ramdisk)
    try:
        rd = decompress(ramdisk, h["ramdisk_compression"])
        open(f"{outdir}/ramdisk.cpio", "wb").write(rd)
        h["ramdisk_uncompressed_size"] = len(rd)
    except Exception as e:
        print(f"[warn] ramdisk 解压失败: {e}", file=sys.stderr)
    h["kernel_compression"] = detect_comp(kernel)
    h["_source_size"] = len(raw)
    json.dump(h, open(f"{outdir}/header.json", "w"), indent=2, ensure_ascii=False)
    print(f"拆包完成 -> {outdir}")
    print(f"  page_size      : {p}")
    print(f"  header_version : {h['header_version']}   os_version: {os_version_str(h['os_version'])}")
    print(f"  kernel         : {h['kernel_size']} bytes ({h['kernel_compression']})  addr=0x{h['kernel_addr']:x}")
    print(f"  ramdisk        : {h['ramdisk_size']} bytes ({h['ramdisk_compression']}) -> {h.get('ramdisk_uncompressed_size','?')}  addr=0x{h['ramdisk_addr']:x}")
    if h.get("dtb_size"): print(f"  dtb            : {h['dtb_size']} bytes")
    print(f"  name           : {h['name']}")
    print(f"  cmdline        : {h['cmdline']}")
    if h["extra_cmdline"]: print(f"  extra_cmdline  : {h['extra_cmdline']}")

def repack(indir, out):
    h = json.load(open(f"{indir}/header.json"))
    p = h["page_size"]
    kernel = open(f"{indir}/kernel", "rb").read()
    if os.path.exists(f"{indir}/ramdisk.cpio"):
        rd = open(f"{indir}/ramdisk.cpio", "rb").read()
        comp = h.get("ramdisk_compression", "gzip")
        ramdisk = compress(rd, comp) if comp != "none" else rd
    else:
        ramdisk = open(f"{indir}/ramdisk.orig", "rb").read()
    dtb = open(f"{indir}/dtb", "rb").read() if os.path.exists(f"{indir}/dtb") else b""
    second = open(f"{indir}/second", "rb").read() if os.path.exists(f"{indir}/second") else b""

    hv = h.get("header_version", 0)
    hdr = bytearray(p)
    hdr[0:8] = MAGIC
    struct.pack_into("<I", hdr, 8, len(kernel))
    struct.pack_into("<I", hdr, 12, h["kernel_addr"])
    struct.pack_into("<I", hdr, 16, len(ramdisk))
    struct.pack_into("<I", hdr, 20, h["ramdisk_addr"])
    struct.pack_into("<I", hdr, 24, len(second))
    struct.pack_into("<I", hdr, 28, h["second_addr"])
    struct.pack_into("<I", hdr, 32, h["tags_addr"])
    struct.pack_into("<I", hdr, 36, p)
    struct.pack_into("<I", hdr, 40, hv)
    struct.pack_into("<I", hdr, 44, h.get("os_version", 0))
    hdr[48:64] = h.get("name", "").encode()[:16].ljust(16, b"\x00")
    hdr[64:576] = h.get("cmdline", "").encode()[:512].ljust(512, b"\x00")
    hdr[576:608] = bytes.fromhex(h["id"]) if h.get("id") else bytes(32)
    hdr[608:1632] = h.get("extra_cmdline", "").encode()[:1024].ljust(1024, b"\x00")
    if hv >= 1:
        struct.pack_into("<I", hdr, 1632, 0)
        struct.pack_into("<Q", hdr, 1636, 0)
        struct.pack_into("<I", hdr, 1644, 1660)
    if hv >= 2:
        struct.pack_into("<I", hdr, 1648, len(dtb))
        struct.pack_into("<Q", hdr, 1652, h.get("dtb_addr", 0))

    outb = bytearray()
    outb += hdr
    outb += kernel.ljust(align(len(kernel), p), b"\x00")
    outb += ramdisk.ljust(align(len(ramdisk), p), b"\x00")
    if len(second): outb += second.ljust(align(len(second), p), b"\x00")
    if hv >= 1: outb += bytes(0)  # recovery_dtbo 为空
    if hv >= 2 and len(dtb): outb += dtb.ljust(align(len(dtb), p), b"\x00")
    open(out, "wb").write(outb)
    print(f"打包完成 -> {out}  ({len(outb)} bytes, kernel={len(kernel)}, ramdisk={len(ramdisk)}({h.get('ramdisk_compression')}), dtb={len(dtb)})")

def rd_unpack(ramdisk, outdir):
    d = decompress(open(ramdisk, "rb").read(), "guess")
    os.makedirs(outdir, exist_ok=True)
    subprocess.run(["cpio", "-idm", "--no-absolute-filenames", "--quiet"], input=d, cwd=outdir, check=True)
    print(f"ramdisk 解开 -> {outdir} ({len(d)} bytes)")

def rd_pack(d, out):
    names = subprocess.run(["bash", "-c", "find . | cpio -o -H newc --quiet"], cwd=d,
                           capture_output=True, check=True).stdout
    if out.endswith(".gz"):
        names = gzip.compress(names, 9, mtime=0)
    open(out, "wb").write(names)
    print(f"ramdisk 打包 -> {out} ({len(names)} bytes)")

def info(img):
    h = parse_header(open(img, "rb").read())
    for k, v in h.items():
        if k in ("os_version",): v = f"{v} => {os_version_str(v)}"
        if isinstance(v, int) and k.endswith("_addr"): v = f"0x{v:x}"
        print(f"{k:24s}: {v}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    a = sys.argv[2:]
    if cmd == "unpack":   unpack(a[0], a[1])
    elif cmd == "repack": repack(a[0], a[1])
    elif cmd == "info":   info(a[0])
    elif cmd == "rd-unpack": rd_unpack(a[0], a[1])
    elif cmd == "rd-pack":   rd_pack(a[0], a[1])
    else: print(__doc__)
