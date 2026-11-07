#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
boot.img 重打包（Gate 1 的核心工具，纯本地、不依赖 mkbootimg）
================================================================
为什么需要自己写：
  1) 64 位 Image **必须**装在 2 MiB 对齐地址（MTK 惯例 0x40080000），
     而本机原厂 boot.img 的 kernel_addr = 0x40008000（32 位 zImage 的地址）。
     若沿用旧地址刷 64 位内核，ATF 在入口处读不到 ARM64 magic，会判成
     "Kernel is 32Bit" 并直接跑飞 —— 这极可能就是上次 bootloop 的真因。
  2) vbmeta 已 disable-verity/verification，boot 不需要重新签名，改完即可刷。

用法：
  python repack_boot.py --src 原厂boot.img --kernel Image \\
      --kernel-addr 0x40080000 --out boot64.img
  # 顺手把 cmdline 里的 bootopt 改成 64 位声明（A/B 都值得先试）
  python repack_boot.py --src boot.img --kernel Image --bootopt 64S3,64S1,64S1 --out boot64.img
"""
import argparse
import struct
import sys

P = struct.Struct("<8s10I16s512s32s1024s")  # boot image header v0-v2


def parse(blob):
    magic, ksz, kaddr, rsz, raddr, ssz, saddr, tags, page, hv, osv, name, cmd, _id, extra = P.unpack_from(blob, 0)
    if magic != b"ANDROID!":
        sys.exit("不是 Android boot image")
    if hv not in (0, 1, 2):
        sys.exit(f"header v{hv} 布局不同，本脚本只处理 v0-v2")
    return dict(kernel_size=ksz, kernel_addr=kaddr, ramdisk_size=rsz, ramdisk_addr=raddr,
                second_size=ssz, second_addr=saddr, tags_addr=tags, page_size=page,
                header_version=hv, os_version=osv, name=name, cmdline=cmd,
                id=_id, extra=extra)


def align(n, page):
    return (n + page - 1) // page * page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="原厂 boot.img（readback 里那份）")
    ap.add_argument("--kernel", help="新内核（Image 或 zImage）；不给则只改 cmdline")
    ap.add_argument("--kernel-addr", default=None, help="如 0x40080000")
    ap.add_argument("--bootopt", default=None, help="替换 cmdline 里的 bootopt=... 值")
    ap.add_argument("--no-dtb", action="store_true", help="不继承源镜像的 DTB")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    raw = open(a.src, "rb").read()
    h = parse(raw)
    page = h["page_size"]
    print(f"[*] 源: {a.src}  page={page} hdr=v{h['header_version']} "
          f"kernel={h['kernel_size']}B@{h['kernel_addr']:#x} ramdisk={h['ramdisk_size']}B")

    off = page
    kernel = raw[off:off + h["kernel_size"]]
    off += align(h["kernel_size"], page)
    ramdisk = raw[off:off + h["ramdisk_size"]]

    if a.kernel:
        kernel = open(a.kernel, "rb").read()
        # 64 位 Image 的判定：偏移 0x38 处应为 'ARM\\x64'
        is64 = kernel[0x38:0x3c] == b"ARM\x64"
        print(f"[*] 新内核 {len(kernel)}B  ARM64 magic={'是' if is64 else '否（可能是 zImage）'}")
        if is64 and a.kernel_addr is None:
            a.kernel_addr = "0x40080000"
            print("[!] 检测到 64 位 Image，kernel_addr 自动切到 0x40080000")

    kaddr = int(a.kernel_addr, 16) if a.kernel_addr else h["kernel_addr"]

    cmd = h["cmdline"].split(b"\0")[0].decode("latin1")
    if a.bootopt:
        import re
        if "bootopt=" in cmd:
            cmd = re.sub(r"bootopt=[0-9A-Za-z,]+", f"bootopt={a.bootopt}", cmd)
        else:
            cmd = (cmd + f" bootopt={a.bootopt}").strip()
        print(f"[*] cmdline bootopt -> {a.bootopt}")
    cmd_b = cmd.encode("latin1")

    hdr = P.pack(b"ANDROID!", len(kernel), kaddr, len(ramdisk), h["ramdisk_addr"],
                 0, h["second_addr"], h["tags_addr"], page, h["header_version"],
                 h["os_version"], h["name"], cmd_b, h["id"], h["extra"])
    out = hdr + b"\0" * (page - len(hdr)) + kernel + b"\0" * (align(len(kernel), page) - len(kernel)) + ramdisk

    # —— 保留源镜像的 DTB —— 
    # MTK 的 boot.img 布局是 header + kernel + ramdisk + DTB，
    # 丢了 DTB，arm64 内核拿不到设备树，会在最早一步直接死（无任何日志）。
    if not a.no_dtb:
        src_tail = align(h["kernel_size"], page) + align(h["ramdisk_size"], page)
        dtb_off = None
        for cand in range(page + src_tail, min(page + src_tail + 0x10000, len(raw)), 4):
            if raw[cand:cand + 4] == b"\xd0\x0d\xfe\xed":
                dtb_off = cand
                break
        if dtb_off:
            total = struct.unpack(">I", raw[dtb_off + 4:dtb_off + 8])[0]
            if 0 < total <= len(raw) - dtb_off:
                dtb = raw[dtb_off:dtb_off + total]
                out += b"\0" * (align(len(out), page) - len(out))
                out += dtb
                print(f"[+] 保留 DTB：源偏移 0x{dtb_off:X}，{total} 字节")
            else:
                print("[!] DTB 头长度异常，跳过")
        else:
            print("[!] 源镜像 ramdisk 之后没有找到 FDT —— 这个镜像可能本来就不带 DTB")

    out += b"\0" * (align(len(out), page) - len(out))

    open(a.out, "wb").write(out)
    print(f"[+] 写出 {a.out}  {len(out)/1048576:.2f} MiB  "
          f"(boot 分区上限 32.00 MiB)  kernel@{kaddr:#x}")
    if len(out) > 32 * 1024 * 1024:
        print("[!] 超出 boot 分区容量，刷不进去，先裁内核/换 lz4 压缩")


if __name__ == "__main__":
    main()
