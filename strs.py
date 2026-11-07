#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 preloader / lk / tee 中查找字符串与 A32->A64 切换指令"""
import os, re

D = r"D:/IMG/ydt1/GeekFlashTool_Readback_20260927084619708"

def strings(data, minlen=4):
    out = []
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, data):
        out.append((m.start(), m.group().decode("latin1")))
    return out

KW = ["arm64", "aarch64", "AARCH64", "ARM64", "64bit", "64-bit", "64 bit",
      "jump64", "bldr", "TZ_INIT", "BL2", "BL31", "el3", "EL3", "EL2", "el2",
      "spsr", "SPSR", "eret", "ERET", "mt6761", "MT6761", "mt6765", "MT6765",
      "lk", "LK", "boot_linux", "boot_arm", "psci", "PSCI", "atf", "ATF",
      "secure", "SBC", "seccfg", "fastboot", "logo"]

# AArch32 -> AArch64 相关编码
PAT = {
    "A32 eret (6e 00 60 e1)":  rb"\x6e\x00\x60\xe1",
    "A32 smc  (70 00 60 e1)":  rb"\x70\x00\x60\xe1",
    "A32 hvc  (70 00 40 e1)":  rb"\x70\x00\x40\xe1",
    "A64 smc  (03 00 00 d4)":  rb"\x03\x00\x00\xd4",
    "A64 hvc  (02 00 00 d4)":  rb"\x02\x00\x00\xd4",
    "A64 eret (e0 03 9f d6)":  rb"\xe0\x03\x9f\xd6",
}

def report(fn):
    p = os.path.join(D, fn)
    if not os.path.exists(p):
        return
    d = open(p, "rb").read()
    print("=" * 80)
    print(f"### {fn}  ({len(d):,} bytes)")
    print("-- 指令/切换特征 --")
    for k, v in PAT.items():
        n = len(re.findall(v, d, re.S))
        if n:
            print(f"   {k:<26} {n}")
    print("-- 关键字命中 --")
    ss = strings(d, 4)
    seen = {}
    for off, s in ss:
        low = s.lower()
        for kw in KW:
            if kw.lower() in low and len(s) < 60:
                seen.setdefault(s, off)
                break
    for s, off in list(seen.items())[:120]:
        print(f"   0x{off:08x}  {s}")

for f in ["preloader_phd162_hd_e47.bin", "lk.img", "tee1.img"]:
    report(f)
