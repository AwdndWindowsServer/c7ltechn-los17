#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sdat2img.py -- 将 LineageOS/AOSP 块差分 OTA 的 *.new.dat(.br/.gz/.xz) + *.transfer.list 还原为 raw 镜像。

支持的 transfer.list 版本: 1/2/3/4
v4 行格式:  <op> <n>,<arg1>,...,<argn>     n = 参数个数(偶数)，参数按 (start,end) 成对解释
命令: new (从 dat 顺序取数), zero (写零), erase (写零/留空洞)

  python3 sdat2img.py <transfer.list> <new.dat[.br|.gz|.xz]> <out.img>
  python3 sdat2img.py --info <transfer.list>     # 只打印头部与镜像尺寸
内存友好：dat 通过管道流式读取，输出用 seek+truncate 生成稀疏文件。
"""
import gzip, io, lzma, os, subprocess, sys

BS = 4096

def parse(tl):
    lines = [l.strip() for l in open(tl, "r", errors="replace") if l.strip()]
    ver = int(lines[0]); total = int(lines[1]); i = 2
    if ver >= 3: i += 1
    if ver >= 4: i += 1
    cmds = []
    for ln in lines[i:]:
        parts = ln.split(None, 1)
        op = parts[0]
        nums = [int(x) for x in parts[1].split(",")] if len(parts) > 1 else []
        if nums and nums[0] == len(nums) - 1:
            nums = nums[1:]                      # 去掉前导参数个数
        cmds.append((op, nums))
    return ver, total, cmds

def ranges(nums):
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]

def info(tl):
    ver, total, cmds = parse(tl)
    mx = 0; dat_blocks = 0
    for op, nums in cmds:
        for s, e in ranges(nums):
            mx = max(mx, e)
            if op in ("new", "diff"): dat_blocks += e - s
    print(f"transfer.list v{ver}: {len(cmds)} 条命令, 头部 total_blocks={total}")
    print(f"  输出镜像 = {mx*BS} bytes ({mx/1024/1024:.1f} MiB, {mx} blocks)")
    print(f"  dat 数据量 = {dat_blocks*BS} bytes ({dat_blocks/1024/1024:.1f} MiB)")

def dat_stream(path):
    """返回 (文件对象, 是否为裸 dat)。流式，不整体读入内存。"""
    with open(path, "rb") as f: sig = f.read(6)
    if sig[:4] == b"\xce\xb2\xcf\x81" or path.endswith(".br"):
        p = subprocess.Popen(["brotli", "-d", "-c", path], stdout=subprocess.PIPE, bufsize=1 << 20)
        return p.stdout, p
    if sig[:2] == b"\x1f\x8b" or path.endswith(".gz"):
        p = subprocess.Popen(["gzip", "-dc", path], stdout=subprocess.PIPE, bufsize=1 << 20)
        return p.stdout, p
    if sig[:6] == b"\xfd7zXZ\x00" or path.endswith(".xz"):
        p = subprocess.Popen(["xz", "-dc", path], stdout=subprocess.PIPE, bufsize=1 << 20)
        return p.stdout, p
    return open(path, "rb"), None

def convert(tl, dat, out):
    ver, total, cmds = parse(tl)
    mx = max(e for _, n in cmds for _, e in ranges(n))
    src, proc = dat_stream(dat)
    written = 0
    with open(out, "wb") as f:
        f.truncate(mx * BS)
        for op, nums in cmds:
            for s, e in ranges(nums):
                f.seek(s * BS)
                nb = (e - s) * BS
                if op in ("new", "diff"):
                    left = nb
                    while left:
                        chunk = src.read(min(left, 1 << 22))
                        if not chunk:
                            raise SystemExit(f"!! dat 数据不足 (还差 {left} 字节)")
                        f.write(chunk); left -= len(chunk)
                    written += nb
                    if proc is None and hasattr(src, "read"):
                        pass
                # zero / erase: 输出文件新建即为全零，保持空洞即可（不写，省时间省空间）
    if proc: proc.wait()
    print(f"[ok] {out}: {os.path.getsize(out)} bytes ({mx} blocks), 数据 {written*1.0/1e6:.1f} MB")

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "--info": info(a[1])
    else: convert(a[0], a[1], a[2])
