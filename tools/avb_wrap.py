#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AVB 结构重排：把内核镜像包成"LK 认得"的完整 boot 分区镜像
============================================================
问题：MTK 的 boot 分区布局是

    [0, N)             kernel + ramdisk + dtb
    [N, N+1472)        vbmeta 结构（AVB hash descriptor）
    [..., P-64)        填充 0
    [P-64, P)          AVB footer（记录 N、vbmeta 偏移/大小）

直接 fastboot flash 一个只有 N 字节的新镜像时，如果 N > 原来的 9,781,248，
就会把 vbmeta 那 1,472 字节覆盖成内核数据 —— LK 按 footer 去读，读到乱码，
于是停在 logo 不启动（实测：原厂镜像只改 1 字节但保持 32 MiB 大小，能正常开机）。

本工具把新镜像按原厂布局重新排好：镜像 → vbmeta → 填充 → 新 footer。

用法：
  python tools/avb_wrap.py --img boot64f.img --src current_boot.img --out boot64g.img
"""
import argparse
import struct

FOOTER_SZ = 64


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True, help="待包装的裸镜像")
    ap.add_argument("--src", required=True, help="原厂 boot 分区镜像（提供 vbmeta 与分区大小）")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    src = open(a.src, "rb").read()
    img = open(a.img, "rb").read()

    magic, vmaj, vmin, orig_size, vmeta_off, vmeta_sz = struct.unpack(">4sIIQQQ", src[-FOOTER_SZ:][:36])
    if magic != b"AVBf":
        raise SystemExit("源镜像尾部没有 AVB footer")
    part = len(src)
    vbmeta = src[vmeta_off:vmeta_off + vmeta_sz]
    print(f"[*] 分区 {part} B | 原镜像 {orig_size} B | vbmeta @{vmeta_off} 大小 {vmeta_sz}")
    print(f"[*] 新镜像 {len(img)} B ({len(img)/1048576:.2f} MiB)")

    if len(img) + vmeta_sz + FOOTER_SZ > part:
        raise SystemExit("新镜像太大，装不下 vbmeta + footer")

    out = bytearray(img)
    new_off = len(out)                      # vbmeta 紧跟镜像
    out += vbmeta
    out += b"\0" * (part - FOOTER_SZ - len(out))

    footer = struct.pack(">4sIIQQQ", b"AVBf", vmaj, vmin, len(img), new_off, vmeta_sz)
    footer += b"\0" * (FOOTER_SZ - len(footer))
    out += footer

    open(a.out, "wb").write(bytes(out))
    print(f"[+] 写出 {a.out}  {len(out)/1048576:.2f} MiB")
    print(f"    布局: 镜像[0,{len(img)})  vbmeta[{new_off},{new_off+vmeta_sz})  footer[末 64B]")
    # 自检：重新解析
    m2, _, _, os2, vo2, vs2 = struct.unpack(">4sIIQQQ", bytes(out[-FOOTER_SZ:][:36]))
    print(f"[✓] 自检 footer: magic={m2} image_size={os2} vbmeta_off={vo2} vbmeta_size={vs2}")


if __name__ == "__main__":
    main()
