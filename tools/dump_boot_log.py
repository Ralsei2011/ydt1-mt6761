#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出 preloader + LK 的 UART 日志（MTK / fastboot）
=================================================
原理：MTK 的 LK 支持 `oem dump_pllk_log`，会把 preloader 与 LK 的串口日志
分块通过 fastboot 吐出来。fastboot 客户端按 ~20 字符切块，需要重新拼装。

用法：
  python tools/dump_boot_log.py                 # 抓一次，存 logs/pllk_<时间>.txt
  python tools/dump_boot_log.py -o my.log       # 指定输出
  python tools/dump_boot_log.py --key           # 只打印关键行（内核装载/位宽/错误）

前置：设备必须在 fastboot 模式（`adb reboot bootloader` 或长按电源+音量下）
"""
import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys

KEY_PAT = re.compile(
    r"bootopt|kernel|K64|jump|spsr|avb|boot image|dtb|error|fail|warn|abort|panic",
    re.I,
)


def run_fastboot(timeout=90):
    exe = shutil.which("fastboot")
    if not exe:
        sys.exit("找不到 fastboot，请确认它在 PATH 里")
    try:
        p = subprocess.run([exe, "oem", "dump_pllk_log"],
                           capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"")
        return out.decode("utf-8", "replace")
    return (p.stdout + p.stderr).decode("utf-8", "replace")


def reassemble(raw):
    """fastboot 客户端每块输出一行并加 '(bootloader) ' 前缀；
    每个块尾部被客户端补了一个换行，数据里真正的换行会表现为空行。"""
    buf = []
    for line in raw.split("\n"):
        if line.startswith("(bootloader) "):
            buf.append(line[len("(bootloader) "):])
        elif line.startswith("(bootloader)"):
            buf.append(line[len("(bootloader)"):])
        elif line.strip() == "":
            buf.append("\n")          # 空行 = 数据中的真实换行
        else:
            buf.append(line)
    text = "".join(buf)
    return re.sub(r"\n{3,}", "\n\n", text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out")
    ap.add_argument("--key", action="store_true", help="只打印关键行")
    ap.add_argument("--timeout", type=int, default=90)
    a = ap.parse_args()

    print("[*] 正在向设备请求 oem dump_pllk_log …")
    raw = run_fastboot(a.timeout)
    if "OKAY" not in raw and "bootloader" not in raw:
        sys.exit("设备可能不在 fastboot 模式，或该 LK 不支持此命令")

    text = reassemble(raw)
    lines = text.splitlines()

    out = a.out
    if not out:
        os.makedirs("logs", exist_ok=True)
        out = os.path.join("logs", "pllk_%s.txt" %
                           datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    open(out, "w", encoding="utf-8").write(text)
    print(f"[+] 已保存 {out}  ({len(lines)} 行, {len(text)} 字符)")

    keys = [l for l in lines if KEY_PAT.search(l)]
    print(f"[*] 关键行 {len(keys)} 条：")
    for l in keys[-40:] if a.key else keys[:40]:
        print("   ", l[:160])
    if not a.key and len(keys) > 40:
        print(f"    …其余 {len(keys)-40} 条见文件，或加 --key 看最后 40 条")


if __name__ == "__main__":
    main()
