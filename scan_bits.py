#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描 MTK 各引导镜像里的 32 位 / 64 位指令特征，判断实际编译位宽。"""
import os, sys, struct, re

D = r"D:/IMG/ydt1/GeekFlashTool_Readback_20260927084619708"
FILES = ["preloader_phd162_hd_e47.bin", "lk.img", "lk2.img", "tee1.img", "tee2.img",
         "gz1.img", "gz2.img", "scp1.img", "sspm_1.img", "spmfw.img", "md1img.img",
         "boot.img", "recovery.img", "dtbo.img"]

# ---- AArch64 特征 ----
A64 = {
    "stp x29,x30,[sp,#-N]!": rb"\xfd\x7b[\x00-\xff]\xa9",
    "ret (c0 03 5f d6)":     rb"\xc0\x03\x5f\xd6",
    "nop (1f 20 03 d5)":     rb"\x1f\x20\x03\xd5",
    "mrs xN,midr_el1":       rb"[\x00-\x1f]\x00\x38\xd5",
    "msr vbar_el1,xN":       rb"[\x00-\x1f]\xc0\x18\xd5",
    "eret (e0 03 9f d6)":    rb"\xe0\x03\x9f\xd6",
    "mov xN,xN (aa..)":      rb"\xaa[\x00-\xff][\x00-\xff]\xaa",
    "adrp xN,":              rb"[\x00-\x1f][\x00-\xff][\x00-\xff]\x90",
}
# ---- AArch32 特征 ----
A32 = {
    "push {..,lr}":          rb"[\x00-\xff][\x2d\x2e\x2f\xe9]",
    "pop {..,pc}":           rb"[\x00-\xff][\xbd\xbe\xbf\xe8]",
    "mrc p15,c0,c0,0(midr)": rb"\x10\x0f\x10\xee",
    "cmp rN,#0 (e3500000)":  rb"[\x00-\x0f]0\x50\xe3",
    "bx lr (1e ff 2f e1)":   rb"\x1e\xff\x2f\xe1",
    "nop (00 f0 20 e3)":     rb"\x00\xf0\x20\xe3",
}

def load(p):
    with open(p, "rb") as f:
        return f.read()

def find_payload(d):
    """跳过 MTK 头部 / 前置零，返回 (偏移, 数据)"""
    if d[:4] == b"\x88\x16\x88\x58" or d[:3] == b"MMM":
        # 头部 512 字节，之后找第一段非零
        for off in (0x200, 0x800, 0x1000):
            if len(d) > off and d[off:off+64].strip(b"\x00"):
                return off, d[off:]
        return 0x200, d[0x200:]
    off = 0
    while off < len(d) - 4 and d[off] == 0:
        off += 1
    return off, d[off:]

def count(data, pats):
    return {k: len(re.findall(v, data, re.S)) for k, v in pats.items()}

def main():
    print(f"{'file':<28}{'size':>10}{'payload':>9}  A64_score  A32_score   verdict")
    print("-" * 92)
    r = {}
    for fn in FILES:
        p = os.path.join(D, fn)
        if not os.path.exists(p):
            continue
        d = load(p)
        off, pd = find_payload(d)
        a64 = count(pd, A64); a32 = count(pd, A32)
        s64 = a64["stp x29,x30,[sp,#-N]!"] + a64["ret (c0 03 5f d6)"] + a64["nop (1f 20 03 d5)"]
        s32 = a32["push {..,lr}"] + a32["pop {..,pc}"] + a32["mrc p15,c0,c0,0(midr)"]
        verdict = "AArch64" if s64 > s32 * 3 and s64 > 50 else ("AArch32" if s32 > s64 * 3 and s32 > 50 else "? unclear")
        r[fn] = (s64, s32, a64, a32)
        print(f"{fn:<28}{len(d):>10}{off:>9}  {s64:>9}  {s32:>9}   {verdict}")
    print("\n--- 明细 ---")
    for fn, (s64, s32, a64, a32) in r.items():
        print(f"\n[{fn}]  A64={s64}  A32={s32}")
        print("  A64:", {k: v for k, v in a64.items() if v})
        print("  A32:", {k: v for k, v in a32.items() if v})

if __name__ == "__main__":
    main()
