#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
expdb 引导日志取证工具 —— 无串口环境下唯一可靠的"开机黑屏也能看到死在哪"的通道
================================================================================
原理：MTK LK 每次启动会把 *上一次* 的 RAM log（preloader/LK/ATF/kernel 全链）
      冲进 expdb 分区，形成环形日志。所以崩溃 → 再开机一次 → 读 expdb，
      就能看到崩溃那次的完整日志。已在 YDT1 上实测验证（3 份历史启动记录）。

用法：
    python expdb_log.py                 # 拉取并打印所有启动记录的关键节点
    python expdb_log.py --grep 关键字    # 只打印含关键字的行（含上下文）
    python expdb_log.py --raw out.txt    # 导出去掉二进制噪声的纯文本
    python expdb_log.py --file expdb.img # 分析已有镜像（不连设备）

依赖：仅 adb（可选）。纯标准库。
"""
import argparse
import os
import re
import subprocess
import sys

PART = "/dev/block/by-name/expdb"
ANCHORS = [
    b"Kernel is 64Bit", b"Kernel is 32Bit",
    b"Secondary bootloader is", b"bootopt=",
    b"[ATF]", b"RAM_CONSOLE start", b"Booting",
]
PRINTABLE = re.compile(rb"[\x20-\x7e\n\r\t]{6,}")


def pull(path: str) -> bool:
    """adb 拉取整个 expdb 分区。"""
    try:
        subprocess.run(["adb", "root"], capture_output=True, timeout=30)
        with open(path, "wb") as f:
            r = subprocess.run(["adb", "exec-out", f"dd if={PART} 2>/dev/null"],
                               stdout=f, timeout=180)
        return r.returncode == 0 and os.path.getsize(path) > 1 << 20
    except Exception as e:  # noqa: BLE001
        print(f"[!] 拉取失败: {e}", file=sys.stderr)
        return False


def to_text(blob: bytes) -> str:
    txt = b"\n".join(PRINTABLE.findall(blob))
    return txt.decode("latin1")


def boot_records(blob: bytes):
    """按 'Kernel is 32Bit/64Bit' 切分启动记录，每份给前后窗口。"""
    hits = [m for m in re.finditer(rb"Kernel is (32|64)Bit", blob)]
    recs = []
    for i, m in enumerate(hits):
        start = max(0, m.start() - 40000)
        end = m.end() + 8000
        if i + 1 < len(hits):
            end = min(end, hits[i + 1].start())
        recs.append((m.start(), m.group(0).decode(), to_text(blob[start:end])))
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="直接分析本地镜像")
    ap.add_argument("--grep", help="只显示匹配行（不区分大小写）")
    ap.add_argument("--raw", help="全量纯文本导出到文件")
    ap.add_argument("--out", default="expdb_full.bin", help="拉取时的落地文件")
    a = ap.parse_args()

    path = a.file or a.out
    if not a.file:
        if not os.path.exists(path) or os.path.getsize(path) < 1 << 20:
            print(f"[*] 从设备拉取 {PART} …")
            if not pull(path):
                sys.exit(2)
        else:
            print(f"[*] 复用已有 {path}（要重新拉取请先删除）")

    blob = open(path, "rb").read()
    print(f"[*] 镜像 {len(blob)/1048576:.1f} MiB  {path}")

    if a.raw:
        open(a.raw, "w", encoding="utf-8", errors="replace").write(to_text(blob))
        print(f"[+] 纯文本已导出 -> {a.raw}")
        return

    if a.grep:
        pat = re.compile(a.grep.encode(), re.I)
        n = 0
        for line in to_text(blob).splitlines():
            if pat.search(line.encode("latin1", "ignore")):
                print(line)
                n += 1
        print(f"[*] 命中 {n} 行")
        return

    recs = boot_records(blob)
    print(f"[*] 找到 {len(recs)} 份启动记录（旧→新）\n")
    for idx, (off, kind, text) in enumerate(recs, 1):
        print("=" * 70)
        print(f"记录 {idx}  @0x{off:X}   {kind}")
        print("=" * 70)
        for line in text.splitlines():
            if any(k in line for k in
                   ("[ATF]", "Kernel is", "bootopt", "Secondary bootloader",
                    "Booting", "RAM_CONSOLE", "cmdline:", "seccfg", "GPT_PL")):
                print("  " + line.strip()[:200])
        print()
    print("[提示] 关键判据：ATF 打的是 'Kernel is 64Bit' 才说明 64 位内核被接受；")
    print("       紧接着的 pc= 应是 0x40080000（AArch64 Image 装载点），32 位是 0x40008000。")


if __name__ == "__main__":
    main()
