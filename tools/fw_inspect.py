#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
供体固件体检：拿到一份 k61v1_64_bsp 固件后，先判断"能不能换到本机"
========================================================================
检查项：
  1. preloader / lk / tee1 / tee2 是否存在，尺寸是否装得进本机分区
  2. lk 到底是 AArch32 还是 AArch64（关键：我们要的是 64 位 LK）
  3. ATF(tee1) 的版本与 BL31 尺寸（TZRAM 只有 0x27800，装不下就白搭）
  4. 分区表对比（本机 scatter vs 供体 scatter）

用法：
  python tools/fw_inspect.py --dir <固件解压目录>
  python tools/fw_inspect.py --dir <目录> --scatter <供体scatter>
"""
import argparse
import glob
import os
import re
import struct


def parse_scatter(p):
    names, sizes = [], []
    if not os.path.exists(p):
        return {}
    for line in open(p, encoding="utf-8", errors="replace"):
        s = line.strip()
        if s.startswith("partition_name:"):
            names.append(s.split(":", 1)[1].strip())
        elif s.startswith("partition_size:"):
            sizes.append(int(s.split(":", 1)[1].strip(), 16))
    return dict(zip(names, sizes))


def arch_of_lk(path):
    """粗判 LK 是 AArch32 还是 AArch64：
    AArch64 常见序言 stp x29,x30,[sp,#-N]! = 0xA9Bxxxxx；AArch32 常见 push {..,lr} = 0xE92D4xxx"""
    d = open(path, "rb").read(0x40000)
    a64 = a32 = 0
    for i in range(0x200, min(len(d) - 4, 0x40000), 4):
        w = struct.unpack_from("<I", d, i)[0]
        if (w & 0xFFC00000) == 0xA9800000:   # stp x?, x?, [sp, #imm]!
            a64 += 1
        if (w & 0xFFFF0000) == 0xE92D0000:   # push {..., lr}
            a32 += 1
    return a64, a32


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="固件解压目录")
    ap.add_argument("--scatter", help="供体 scatter（可选）")
    ap.add_argument("--ours", default="D:/IMG/ydt1/GeekFlashTool_Readback_20260927084619708/MT6761_Android_scatter.txt")
    a = ap.parse_args()

    files = {os.path.basename(p).lower(): p for p in glob.glob(os.path.join(a.dir, "*"))}
    ours = parse_scatter(a.ours)
    donor = parse_scatter(a.scatter) if a.scatter else {}

    def find(*keys):
        for k, p in files.items():
            if all(x in k for x in keys):
                return p
        return None

    print("=" * 62)
    print("供体固件体检")
    print("=" * 62)

    # preloader
    pl = find("preloader")
    if pl:
        sz = os.path.getsize(pl)
        limit = ours.get("preloader")
        ok = "✅" if (limit and sz <= limit) else ("⚠️ 未知上限" if not limit else "❌ 超出")
        print(f"preloader : {os.path.basename(pl)}  {sz/1024:.0f} KB  上限 {limit/1048576:.1f} MB  {ok}"
              if limit else f"preloader : {os.path.basename(pl)}  {sz/1024:.0f} KB")
    else:
        print("preloader : 未找到")

    # lk
    lk = find("lk") or find("lplk")
    if lk:
        sz = os.path.getsize(lk)
        a64, a32 = arch_of_lk(lk)
        hint = "AArch64（64位）" if a64 > a32 else "AArch32（32位，不能用）"
        limit = ours.get("lk")
        fit = "✅" if (limit and sz <= limit) else "❌ 超尺寸"
        print(f"lk        : {os.path.basename(lk)}  {sz/1024:.0f} KB  上限 {limit/1048576:.1f} MB  {fit}")
        print(f"            架构判定: {hint}   (A64序言={a64}  A32 push={a32})")
    else:
        print("lk        : 未找到")

    # tee
    for name in ("tee1", "tee2"):
        p = find(name)
        if p:
            sz = os.path.getsize(p)
            limit = ours.get(name)
            fit = "✅" if (limit and sz <= limit) else "❌ 超尺寸"
            ver = ""
            b = open(p, "rb").read(0x1C400)
            m = re.search(rb"BL31: v([\w.\-()]+)", b)
            if m:
                ver = "  ATF " + m.group(1).decode("latin1", "replace")
            tz = re.search(rb"BL31_TZRAM_SIZE=0x([0-9A-Fa-f]+)", b)
            if tz:
                ver += f"  TZRAM=0x{tz.group(1).decode()}"
            print(f"{name:<10}: {os.path.basename(p)}  {sz/1024:.0f} KB  上限 {limit/1048576:.1f} MB  {fit}{ver}")
        else:
            print(f"{name:<10}: 未找到")

    if donor:
        print("\n分区尺寸对比（本机 / 供体）")
        for k in ("preloader", "lk", "tee1", "tee2", "boot", "dtbo"):
            x, y = ours.get(k), donor.get(k)
            if x and y:
                flag = "" if x == y else "   ← 不同"
                print(f"  {k:<10} {x/1048576:6.1f} MB   {y/1048576:6.1f} MB{flag}")

    print("\n提示：TZRAM 只容得下约 158 KB 的 BL31；ATF 体积过大就装不进去。")


if __name__ == "__main__":
    main()
