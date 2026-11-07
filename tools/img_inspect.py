#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
镜像头检视 / 供体比对（Gate 0 用，全程只读，不碰设备）
======================================================
用途：
  1) info  <img>            解析 MTK image header、Android boot header、位宽特征
  2) diff  <本机目录> <供体目录>   逐项对比 lk / boot / dtbo / tee 的关键字段

为什么需要它：
  "位宽开关在 LK 镜像头还是 preloader" 这个问题的答案，70% 可以在静态层面看出来，
  不需要刷机。把两边 lk 的 magic/size/name/maddr/mode + ext 头逐字节摆出来，
  再看各自 boot.img cmdline 里的 bootopt 串，就能定位差异。

用法：
  python img_inspect.py info  D:/IMG/ydt1/.../lk.img
  python img_inspect.py info  D:/IMG/ydt1/.../boot.img
  python img_inspect.py diff  D:/IMG/ydt1/GeekFlashTool_Readback_... D:/IMG/donor/ulefone_note_7p
纯标准库。
"""
import argparse
import os
import re
import struct

MTK_MAGIC = 0x58881688
ANDROID_MAGIC = b"ANDROID!"
VENDOR_MAGIC = b"MTK_BLOADER_INFO_v"


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def mtk_header(blob):
    """MTK image header: magic,size,name[32],maddr,mode (48B) + ext header @0x30"""
    if len(blob) < 48 or u32(blob, 0) != MTK_MAGIC:
        return None
    magic, size = u32(blob, 0), u32(blob, 4)
    name = blob[8:40].split(b"\0")[0].decode("latin1", "replace")
    maddr, mode = u32(blob, 40), u32(blob, 44)
    ext = blob[48:80]
    return {"magic": f"0x{magic:08X}", "size": size, "name": name,
            "maddr": f"0x{maddr:X}", "mode": mode,
            "ext_hex": ext[:32].hex(" "),
            "ext_u32": [f"0x{u32(ext, i):X}" for i in range(0, 32, 4)]}


def boot_header(blob):
    """Android boot image header v0-v2（v3/v4 结构不同，这里只做基础判定）"""
    if blob[:8] != ANDROID_MAGIC:
        return None
    version = u32(blob, 40)
    if version >= 3:
        return {"header_version": version, "note": "v3/v4，字段布局不同，略"}
    h = {
        "kernel_size": u32(blob, 8), "kernel_addr": f"0x{u32(blob, 12):X}",
        "ramdisk_size": u32(blob, 16), "ramdisk_addr": f"0x{u32(blob, 20):X}",
        "second_size": u32(blob, 24), "tags_addr": f"0x{u32(blob, 32):X}",
        "page_size": u32(blob, 36), "header_version": version,
        "os_version": f"0x{u32(blob, 44):X}",
        "name": blob[48:64].split(b"\0")[0].decode("latin1", "replace"),
        "cmdline": blob[64:576].split(b"\0")[0].decode("latin1", "replace").strip(),
    }
    return h


def width_hint(blob):
    """位宽启发式统计：AArch64 函数序言 stp x29,x30,[sp,#-N]! vs AArch32 push{...,lr}"""
    a64 = blob.count(b"\xfd\x7b\xbf\xa9")
    a32 = len(re.findall(rb"[\x00-\xff][\x40-\x4f]\x2d\xe9", blob))
    veredict = "AArch64" if a64 > a32 * 2 else ("AArch32" if a32 > a64 else "混合/无法判定")
    return {"a64_prologue": a64, "a32_push": a32, "verdict": veredict}


def dtb_check(blob):
    if blob[:4] != b"\xd0\x0d\xfe\xed":
        return None
    total = struct.unpack_from(">I", blob, 4)[0]
    return {"dtb_total_size": total, "note": "大端 FDT 头，可后续用 fdt_parse.py 展开"}


def report(path):
    blob = open(path, "rb").read()
    print(f"\n=== {os.path.basename(path)}  ({len(blob):,} B)")
    for fn in (mtk_header, boot_header, dtb_check):
        r = fn(blob)
        if r:
            for k, v in r.items():
                print(f"    {k:14s} {v}")
    w = width_hint(blob)
    print(f"    位宽启发式     {w['verdict']}  (a64序言={w['a64_prologue']}  a32push={w['a32_push']})")
    # bootopt 串：判断 EL 位宽声明的关键
    for m in re.finditer(rb"bootopt=([0-9A-Za-z,]+)", blob):
        s = m.group(1).decode()
        tag = ""
        if "32S1" in s or "32N" in s:
            tag = "  <- 含 32 位 EL1 声明"
        if "64S1" in s:
            tag += "  <- 含 64 位 EL1 声明"
        print(f"    bootopt        {s}{tag}  @0x{m.start():X}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["info", "diff"])
    ap.add_argument("paths", nargs="+")
    a = ap.parse_args()
    if a.cmd == "info":
        for p in a.paths:
            report(p)
    else:
        d1, d2 = a.paths
        names = ["lk.img", "lk2.img", "boot.img", "dtbo.img", "tee1.img"]
        for n in names:
            p1, p2 = os.path.join(d1, n), os.path.join(d2, n)
            have = [os.path.exists(p1), os.path.exists(p2)]
            print(f"\n########## {n}   本机:{have[0]}  供体:{have[1]}")
            for p, ok in ((p1, have[0]), (p2, have[1])):
                if ok:
                    report(p)


if __name__ == "__main__":
    main()
