#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2 探针：ATF 的 SPSR 4 字节补丁（只改 tee1，不碰 preloader / LK）
=================================================================
目的：判定"ATF 以 AArch32 进 BL33"这个决定，是 ATF 自己写死的，还是 preloader 传进来的。

原理：tee1.img 偏移 0x276C 处是一条 `mov w0, #0x1d3`（机器码 0x52803A60），
      0x1d3 = AArch32/SVC/ARM态/屏蔽中断，正是日志里 `SPSR = 0x1d3` 的值。
      把它改成 0x3c5（AArch64/EL1h/屏蔽中断）后开机，读 expdb：
        · 打印 SPSR = 0x3c5  → 开关在 ATF 里，方案 C 有门
        · 仍打印 0x1d3        → 这条常量与 SPSR 无关，开关在 preloader → C 判死
        · 完全没有新日志       → ATF 被校验（SBC/hash），tee 不可改

安全：只写 tee1 分区（可完整刷回）。原镜像 tee1.img 请先备份并核对 MD5
      b366da5c45e555a7a51c98649c97544c

用法：
  python tools/patch_tee.py --check                      # 只核对，不生成
  python tools/patch_tee.py --out tee1_l2.img            # 生成补丁镜像
  python tools/patch_tee.py --restore --out tee1_stock.img  # 从补丁镜像还原
"""
import argparse
import hashlib
import struct
import sys

SRC = "D:/IMG/ydt1/GeekFlashTool_Readback_20260927084619708/tee1.img"
OFF = 0x276C
ORIG = 0x52803A60  # mov w0, #0x1d3
NEW = 0x52800000 | (0x3C5 << 5)  # mov w0, #0x3c5  -> 0x528078A0
MTK_MAGIC = 0x58881688


def load(path):
    d = bytearray(open(path, "rb").read())
    magic = struct.unpack_from("<I", d, 0)[0]
    size = struct.unpack_from("<I", d, 4)[0]
    name = bytes(d[8:40]).split(b"\0")[0].decode("latin1", "replace")
    return d, magic, size, name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()

    d, magic, size, name = load(a.src)
    if magic != MTK_MAGIC:
        sys.exit(f"不是 MTK image（magic=0x{magic:08X}）")
    print(f"[*] {a.src}")
    print(f"    MTK header: magic=0x{magic:08X} name={name!r} size=0x{size:X} ({size/1024:.1f} KB)")
    print(f"    MD5 = {hashlib.md5(bytes(d)).hexdigest()}")

    cur = struct.unpack_from("<I", d, OFF)[0]
    print(f"    @0x{OFF:X} = 0x{cur:08X}  " +
          ("= mov w0,#0x1d3（原厂）" if cur == ORIG else
           ("= mov w0,#0x3c5（已打过补丁）" if cur == NEW else "= 未知指令，别乱改")))

    if cur not in (ORIG, NEW):
        sys.exit("指令与预期不符，停止（可能版本不对）")
    if a.check:
        return

    target = ORIG if a.restore else NEW
    if cur == target:
        print(f"[=] 目标值与当前一致（0x{target:08X}），无需改")
    else:
        struct.pack_into("<I", d, OFF, target)
        print(f"[+] 0x{OFF:X}: 0x{cur:08X} -> 0x{target:08X}")

    if not a.out:
        sys.exit("请用 --out 指定输出文件")
    open(a.out, "wb").write(bytes(d))
    print(f"[+] 写出 {a.out}  {len(d)/1024:.1f} KB / 分区 5 MB")
    print("[!] 刷机命令： fastboot flash tee1 <文件>   回滚： fastboot flash tee1 原厂 tee1.img")


if __name__ == "__main__":
    main()
