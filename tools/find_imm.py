#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在二进制里找"哪条指令生成了某个立即数"（用于判定 SPSR / 位宽模式的来源）
=====================================================================
背景：ATF 退出 EL3 时打印 SPSR = 0x1d3（AArch32 SVC）。要知道这个值从哪来：
  - 若是某条指令里的立即数（mov/movz/orr）→ 编译期写死，改起来容易
  - 若是从内存/结构体 ldr 出来的     → 运行期由 preloader 传入，改起来难
本脚本只做前者：扫所有指令的立即数操作数。

用法：
  python tools/find_imm.py <file> --arch aarch64 --imm 0x1d3 --imm 0x3c5
  python tools/find_imm.py <file> --arch arm --imm 0x1d3 --start 0x200
"""
import argparse
import sys

from capstone import CS_ARCH_ARM, CS_ARCH_ARM64, CS_MODE_ARM, CS_MODE_LITTLE_ENDIAN, Cs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--arch", choices=["arm", "aarch64"], required=True)
    ap.add_argument("--imm", action="append", default=[], help="要搜的立即数，可多次")
    ap.add_argument("--start", default="0", help="起始文件偏移")
    ap.add_argument("--len", default=None, help="扫描长度（默认全文件）")
    ap.add_argument("--ctx", type=int, default=0, help="命中后额外打印前后指令数")
    a = ap.parse_args()

    targets = {int(x, 0) for x in a.imm}
    if not targets:
        sys.exit("至少给一个 --imm")

    blob = open(a.file, "rb").read()
    start = int(a.start, 0)
    end = start + int(a.len, 0) if a.len else len(blob)
    code = blob[start:end]

    if a.arch == "aarch64":
        md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    else:
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    md.skipdata = True  # 遇到非法指令不停，继续线性扫描（镜像里混有数据段）

    insns = list(md.disasm(code, start))
    print(f"[*] {a.file}  arch={a.arch}  解码 {len(insns)} 条  "
          f"目标立即数 {[hex(t) for t in sorted(targets)]}")

    hits = 0
    for i, ins in enumerate(insns):
        if not ins.mnemonic or ins.mnemonic.startswith("."):
            continue  # skipdata 产生的伪指令
        try:
            ops = ins.operands
        except Exception:  # noqa: BLE001
            continue
        for op in ops:
            if getattr(op, "type", None) == 2:  # IMM
                if op.imm in targets:
                    hits += 1
                    lo = max(0, i - a.ctx)
                    hi = min(len(insns), i + a.ctx + 1)
                    print(f"\n--- 0x{ins.address:X}  {ins.mnemonic} {ins.op_str}")
                    if a.ctx:
                        for j in range(lo, hi):
                            mark = ">>" if j == i else "  "
                            print(f"  {mark} 0x{insns[j].address:X}  "
                                  f"{insns[j].mnemonic} {insns[j].op_str}")
    print(f"\n[*] 共 {hits} 处命中")
    if hits == 0:
        print("[结论] 没有指令直接生成这些值 → 该值 100% 来自内存/结构体（运行期传入）")


if __name__ == "__main__":
    main()
