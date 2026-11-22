#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mkqcdt.py — 生成三星 aboot 认的 QCDT v2 表（boot.img 的 dt 区）

  python3 mkqcdt.py <out.dt> <dtb> [msm_id board_id "subtypes"]...

例（C7 / SM-C7000）：
  python3 mkqcdt.py dt.img msm8953-c7ltechn.dtb 293 8 "0 3 4"

表结构（与 qcom dtbtool 一致，24 字节/项）：
  magic "QCDT" (4B) + version=2 (u32) + num_entries (u32)
  每项: msm_id, board_id, subtype, 0, offset, size  —— 每段 dtb 按 4 字节对齐，从头 pad 到 0x800
"""
import struct, sys


def qcdt(dtbs, pad_to=0x800):
    """dtbs: [(blob, [(msm_id, board_id, subtype), ...]), ...]"""
    entries = []
    for blob, keys in dtbs:
        for (msm_id, board_id, subtype) in keys:
            entries.append((msm_id, board_id, subtype, blob))
    off = max(12 + 24 * len(entries), pad_to)
    table = bytearray(b"QCDT")
    table += struct.pack("<II", 2, len(entries))
    body = bytearray()
    for (msm_id, board_id, subtype, blob) in entries:
        table += struct.pack("<IIIIII", msm_id, board_id, subtype, 0,
                             off + len(body), len(blob))
        body += blob
        if len(body) % 4:
            body += b"\0" * (4 - len(body) % 4)
    table += b"\0" * (off - len(table))
    return bytes(table) + bytes(body)


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 1
    out, dtb = argv[1], argv[2]
    msm_id, board_id = int(argv[3], 0), int(argv[4], 0)
    subtypes = [int(x, 0) for x in argv[5].split()] if len(argv) > 5 else [0]
    blob = open(dtb, "rb").read()
    keys = [(msm_id, board_id, st) for st in subtypes]
    data = qcdt([(blob, keys)])
    open(out, "wb").write(data)
    print(f"QCDT: {out}  {len(data)} B  entries={len(keys)}  "
          f"msm_id={msm_id} board_id={board_id} subtypes={subtypes}  dtb={len(blob)} B")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
