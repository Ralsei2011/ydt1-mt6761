#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极简 FDT(dtb) 解析：打印节点路径、关键属性，找 cpus/psci/bootargs"""
import struct, sys, os, re

def be32(b, o): return struct.unpack(">I", b[o:o+4])[0]

def parse(d, base=0):
    magic, totalsize, off_struct, off_strings, off_rsv, ver, lastcomp, bootcpuid, size_strings, size_struct = \
        struct.unpack(">10I", d[base:base+40])
    assert magic == 0xd00dfeed, hex(magic)
    st = d[base+off_struct: base+off_struct+size_struct]
    strs = d[base+off_strings: base+off_strings+size_strings]
    print(f"FDT @0x{base:x} total={totalsize} struct={size_struct} strings={size_strings} ver={ver}")
    def s(off):
        e = strs.find(b"\x00", off)
        return strs[off:e].decode("latin1")
    path = []
    i = 0
    out = []
    while i < len(st):
        tok = be32(st, i); i += 4
        if tok == 1:  # BEGIN_NODE
            e = st.find(b"\x00", i); name = st[i:e].decode("latin1"); i = (e + 4) & ~3
            path.append(name)
        elif tok == 2:  # END_NODE
            if path: path.pop()
        elif tok == 3:  # PROP
            ln, no = be32(st, i), be32(st, i+4); i += 8
            val = st[i:i+ln]; i = (i + ln + 3) & ~3
            out.append(("/".join(path), s(no), val))
        elif tok == 4:  # NOP
            pass
        elif tok == 9:
            break
        else:
            break
    return out

def show(props, keys):
    for p, n, v in props:
        if n in keys:
            if n in ("compatible", "model", "bootargs", "enable-method", "device_type", "status", "method"):
                txt = v.replace(b"\x00", b" ").decode("latin1").strip()
                print(f"  {p or '/' :<40} {n:<16} {txt[:120]}")
            elif n == "reg" and len(v) <= 16:
                print(f"  {p or '/':<40} {n:<16} {[hex(x) for x in struct.unpack('>%dI'%(len(v)//4), v)]}")
            elif n == "cache-line-size" or n == "clock-frequency":
                print(f"  {p or '/':<40} {n:<16} {struct.unpack('>I', v[:4])[0]}")
    print()

if __name__ == "__main__":
    f = sys.argv[1]
    d = open(f, "rb").read()
    base = d.find(b"\xd0\x0d\xfe\xed")
    props = parse(d, base)
    keys = {"compatible", "model", "bootargs", "enable-method", "device_type", "method", "reg", "clock-frequency"}
    print("--- CPU / PSCI / bootargs ---")
    show(props, keys)
    # cpu 节点汇总
    cpus = {}
    for p, n, v in props:
        if n == "compatible" and "arm,cortex" in v.decode("latin1", "ignore"):
            cpus.setdefault("/".join(p.split("/")[:-1]), []).append(v.split(b"\x00")[0].decode())
    print("--- CPU 簇 ---")
    for k, v in cpus.items():
        print(" ", k, len(v), v[:1])
