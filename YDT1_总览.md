# 学习机 YDT1 · 全景交接文档

> 最后更新：2026-11-07 18:20（设备在线，adb 可用）
> 配套文件：`D:/ydt1_work/64位可行性分析.md`（源码调研 + 各层位宽实测）
> 用途：开新对话时，把这份文档丢进去即可接上全部上下文，不用再翻历史。

---

## 0. 三句话现状

1. **这台机器（MT6761，2G/16G，4 核 A53）现在跑的是 LineageOS 20.0（Android 13）的 `a64` GSI，已 root（Magisk Alpha），一切正常。**
2. 它是**纯 32 位 BSP**：preloader/LK/内核/vendor 全是 32 位，只有 ATF 是 64 位 → arm64 系统一律开不了机，只能刷 `a64`/`arm` GSI。
3. 目前唯一在讨论的"大动作"是**底层改 64 位**（结论：只换内核能成但没意义；真 64 位要整机移植同芯片 64 位 ROM），尚未动手。

---

## 1. 设备档案

| 项 | 值 |
|---|---|
| 代号/型号 | `phd162_hd_e47`（preloader 文件名），系统内 `ro.product.device = ydt1` |
| 序列号 | `YDT100280340374` |
| SoC | MediaTek **MT6761**（Helio A22，4×Cortex-A53，12nm），`ro.board.platform=mt6761` |
| 内存/存储 | RAM 1950 MB（2 GB），`/data` 11 G，`super` 2.15 GiB |
| 屏幕 | 720×1280 @ 320 dpi |
| 原厂系统 | Android 10 / SDK 29 / VNDK 29（`ydt1/ydt1/ydt1:10/QP1A.190711.020`），A-only + 动态分区 |
| 原厂内核 | Linux **4.9.190+** armv7l，2021-01-21 编译，GCC 4.9.x |
| 引导链 | BROM → preloader(32) → ATF/BL31(64·EL3) → LK(32) → kernel(armv7l) |
| 安全状态 | **已解锁**：`ro.boot.verifiedbootstate=orange`、`ro.boot.flash.locked=0`；`seccfg` 锁态=0 |
| 特殊点 | `gz1/gz2` 全 0（无虚拟机监控器）；`tee` 分区 5 MB 里只有 113 KB 的 ATF，**没有 TEE OS**（keymaster 是软实现 → 设锁屏密码必崩） |

---

## 2. 当前系统（在线快照）

| 项 | 值 |
|---|---|
| 系统 | `lineage_a64_bvN-userdebug 13 TQ3A.230901.001`（TrebleDroid 的 **a64 = 64 位内核 + 32 位用户态**那一档，这里连内核都是 32 位） |
| 内核 | `4.9.190+ #1 SMP PREEMPT` **armv7l**（恢复成原厂 boot 了，见 §5-③） |
| root | Magisk Alpha `io.github.vvb2060.magisk`，`/sbin/magisk`、`/sbin/su`、`/data/adb/magisk` 齐全；`adb root` 可直接 uid=0 |
| 应用 | 6 个第三方：Magisk、MT管理器×2、Via 浏览器、讯飞输入法、应用市场 |
| 关键设置 | `lockscreen.disabled=1`、`lock_screen_lock_after_timeout=null`（**注意，见 §8**）、`ambient_touch_to_wake=0`、`screen_off_timeout=30000`、`ntp_server=ntp1.aliyun.com` |
| 电量 | 23%，充电中，health=good |

---

## 3. 分区表（scatter 全 39 项，写分区/找地址时直接用）

| 分区 | 大小 | 起始地址 | 备注 |
|---|---|---|---|
| preloader | 0x400000 | 0x0 | 在 EMMC_BOOT1/2 区，**绝对不要动** |
| boot_para | 0x100000 | 0x8000 | |
| recovery | 0x2000000 | 0x108000 | 32 MiB，但实际镜像只用 8.7 MB 内核 + 6.5 MB ramdisk |
| para | 0x80000 | 0x2108000 | |
| expdb | 0x1400000 | 0x2188000 | |
| vbmeta_system | 0x800000 | 0x3588000 | |
| vbmeta_vendor | 0x800000 | 0x3D88000 | |
| frp | 0x100000 | 0x4588000 | |
| nvcfg | 0x2000000 | 0x4688000 | |
| nvdata | 0x4000000 | 0x6688000 | 基带/IMEI 相关，别刷 |
| md_udc | 0x169A000 | 0xA688000 | |
| metadata | 0x2000000 | 0xBD22000 | |
| protect1 | 0x800000 | 0xDD22000 | |
| protect2 | 0xADE000 | 0xE522000 | |
| seccfg | 0x800000 | 0xF000000 | 锁状态 |
| sec1 | 0x200000 | 0xF800000 | |
| proinfo | 0x300000 | 0xFA00000 | |
| md1img | 0x6400000 | 0xFD00000 | 基带固件 |
| spmfw | 0x100000 | 0x16100000 | |
| scp1 / scp2 | 0x100000 ×2 | 0x16200000 / 0x16300000 | |
| sspm_1 / sspm_2 | 0x100000 ×2 | 0x16400000 / 0x16500000 | |
| gz1 / gz2 | 0x1000000 ×2 | 0x16600000 / 0x17600000 | **全 0，空的** |
| nvram | 0x4000000 | 0x18600000 | WiFi/BT 校准，别刷 |
| **lk** | 0x100000 | **0x1C600000** | 1 MiB，32 位 |
| lk2 | 0x100000 | 0x1C700000 | 备用槽 |
| **boot** | 0x2000000 | **0x1C800000** | 32 MiB |
| logo | 0x800000 | 0x1E800000 | 开机动画 |
| **dtbo** | 0x800000 | **0x1F000000** | 8 MiB，只用了 32 KB（板级 overlay） |
| tee1 | 0x500000 | 0x1F800000 | ATF 113 KB |
| tee2 | 0xB00000 | 0x1FD00000 | |
| **super** | 0x89504C00 | **0x20800000** | 2,303,740,928 字节（被上一任从 5.91 GiB 砍到这个尺寸） |
| vbmeta | 0xF42400 | 0xA9D04C00 | 16 MB，AVB 签名（RSA2048） |
| cache | 0x1B003A00 | 0xAAC47000 | 尺寸是重排后的怪值 |
| userdata | 0x2DA6B1400 | 0xC5C4AA00 | 11.4 GiB |
| otp | 0x2B00000 | 0x3A02FBE00 | |
| flashinfo | 0x1000000 | 0x3A2DFBE00 | |

---

## 4. 备份与文件索引

### 4.1 全分区读回（两份，内容一致，3.2 GB / 份）
- `D:/IMG/ydt1/GeekFlashTool_Readback_20260927084619708/` ← **推荐用这份**（带 scatter，文件名规范）
- `D:/IMG/ydt1/buckup/` ← 同上，`.bin` 命名

关键文件 MD5（写前核对用）：

| 文件 | MD5 |
|---|---|
| `boot.bin`（= 工作区 `backup/boot.img`） | `b7ebe7327702a45c125e5f77bf1de3bc` |
| `lk.bin` | `c509d232be1e60a97136ea338221e9c2` |
| `tee1.bin` | `b366da5c45e555a7a51c98649c97544c` |
| `gpt.bin` / `gpt_backup.bin` | `91cb214a579b09fa05b717f765329b10` |
| `seccfg.bin` | `c66ef3724cd686f759503673780a10d7` |
| `backup/super_patched.bin`（改过元数据的 256 KB） | `27700997e9db0a3efdcec3fd00742949` |

> ⚠️ 这套备份是**上一任改过之后**拍的（super 已被砍到 2.15 GiB、system 里有 `phhsu_exec`），不是真原厂。

### 4.2 工作文件
| 路径 | 作用 |
|---|---|
| `C:/Users/zengz/WorkBuddy/2026-10-31-20-23-34/backup/boot.img` | 原厂 32 位 boot（救砖主力） |
| 同上 `super_patched.bin` | 修好 liblp 元数据的 256 KB 头，重刷 super 后要补 |
| 同上 `super_head.bin` / `super_flash.sparse` / `mk_sparse.py` | 早期绕路方案（现已不需要） |
| `D:/ydt1_work/64位可行性分析.md` | 64 位改造的调研与实测报告 |
| `D:/ydt1_work/scan_bits.py` | 扫镜像里 AArch32/AArch64 特征（判断任意 lk/内核位宽，可复用） |
| `D:/ydt1_work/strs.py` / `fdt_parse.py` | 引导镜像字符串提取 / DTB 解析（自写，无依赖） |
| `D:/ydt1_work/base.dtb` | 从 boot.img 尾部抽出的**本机完整板级 DTB（85 KB）**，64 位移植要用 |
| 编译盒子（SSH 别名 `ydt1-box`，连接信息只存本地 `~/.ssh/config`） | 上 `/root/build_mt6761.sh`(4.9) `/root/build_duoqin.sh`(4.19)，源码在 `/mnt/sdcard/work/src/` |

---

## 5. 干过的事（时间线，踩过的坑都在里面）

**① 刷 GSI（2026-10-31）**
- 原厂 super 的 liblp 元数据整体偏移 8 KB（geometry 在 0x2000，主/备在 0x3000/0x13000，另有两份 0x23000/0x33000）
- 先用 sparse + DONT_CARE 绕过 `fastboot flash system` 失败，刷入 `lineage-20.0-20251021-a64_bvN`
- 教训：**在运行中的 Android 里 dd 写 system 会写到一半掉线**

**② 修 super 元数据（2026-11-01 12:10，已解决）**
- 根因：上一任把 super 从 5.91 GiB 砍到 2.15 GiB、GPT 整体重写，但 liblp 里 `block_device.size` 还是 6342967296 → 所有分区表提交被拒（`Failed to write partition table`）
- 修法：`patch_super.py` 把 4 份元数据的 size 改成 2303740928 并重算 SHA256 → 刷 256 KB 头
- 结果：`fastboot resize-logical-partition` / `fastboot flash system` 恢复正常，**今后不必再用 sparse 绕行**

**③ 试 64 位内核（2026-11-01，失败已恢复）**
- 4.9 的 alps 树不完整（mt6761 文件 253 vs mt6765 483），换 Duoqin F21 Pro 的 4.19 树，编出 **AArch64 Image**（30 MB）并刷进 boot
- 结果：**开机反复重启** → `fastboot flash boot backup/boot.img` 恢复
- 教训：**这台 LK 引导不了 64 位内核**（也可能是 4.19 内核配 4.9 DT 不匹配，两者都成立）
- 另一个坑：**`fastboot boot` 是假的** —— LK 回 `Booting OKAY` 但根本没加载传入镜像（用 `androidboot.fboottest=1` 标记验证过），只能 `flash`

**④ 熄屏后 5 秒自动亮（2026-11-01 17:05，已修）**
- 不是"抬手亮屏太灵敏"：`lockscreen.disabled=1` 与 `lock_screen_lock_after_timeout=5000` 冲突 → SystemUI 反复 showBouncer
- 修法：`settings put secure lock_screen_lock_after_timeout 86400000`；顺手关 `ambient_touch_to_wake=0`

**⑤ 设锁屏密码崩溃（2026-11-01 17:40，已修）**
- `KeyMint ErrorCode(-26) KEY_USER_NOT_AUTHENTICATED` ← 残留的 `locksettings.db` 指向 auth-bound key，但 `spblob` 目录不存在
- 修法：删 `locksettings.db*` 重建。**结论：这台别设锁屏密码**（无 TEE OS，只能软实现）

**⑥ "反复重启"（2026-11-07 17:25，已修）**
- 其实不是重启：system_server 每 23 秒崩一次（`LockSettingsService: Failed to decrypt blob`），停在 FallbackHome
- 修法（先 `stop` 停框架）：
  ```
  rm -f /data/system/locksettings.db*
  rm -f /data/misc/gatekeeper/*
  rm -rf /data/system/users/0/spblob
  rm -f /data/system/users/0/gatekeeper.*.key /data/system/gatekeeper.*.key
  sync && reboot
  ```
- 必须保住 `/data/misc/vold/user_keys/ce/0/current/`（FBE key，删了数据全丢）
- 结果：78 秒开机，`service check lock_settings` = found，连续观察 187 秒无重启

**⑦ 64 位可行性调研（2026-11-07 17:55）**
- 见 `64位可行性分析.md`。一句话：**硬件天生 64 位**（ATF 现在就是 AArch64 在 EL3 跑），内核 64 位有公开源码，唯一的墙是 **32 位闭源 LK**；就算翻过去，vendor 里 390 个 .so 全是 32 位，用户态还是 32 位。

---

## 6. 坑与禁忌（血泪清单）

1. **preloader 绝对不能刷**：板级 EMI/DRAM 参数编在里面，一错连 BROM 都进不去，只能拆机短接。
2. **别设锁屏密码**：无 TEE OS，必崩（见 §5-⑤⑥）。
3. **`fastboot boot` 无效**：LK 假回 OKAY，实际丢弃镜像，只能 `flash`。
4. **`fastboot boot` 无效**（LK 假回 OKAY），但 **`fastboot flash` 物理分区是好的**（vbmeta/super/userdata/cache 都验证过）；改逻辑分区用 fastbootd（`is-userspace: yes`），实在不行用**刷机匣 GeekFlashTool 自定义地址直写**（走 MTK DA，绕过 bootloader）。
5. **刷 super 前先确认 liblp 元数据是改过的那份**，否则 `fastboot flash system` 会全失败；重刷原厂 `super.bin` 后要重打补丁。
6. **重刷 GSI 会恢复 `/system/xbin/su` 之类**（那是另一台 GT3 的坑，这台没有）。
7. **我的常驻进程会被回收**，GUI 操作只能你手动点；刷机匣这类工具要我指路、你来点。
8. 进 fastboot：长按电源 15 s 关机 → **音量下 + 电源**。

---

## 7. "改 64 位"结论摘要（详见 64位可行性分析.md）

| 层 | 现状 | 可行方案 |
|---|---|---|
| 硬件 | 4×A53，AArch64 可用（ATF 已在跑 64 位） | 无限制 |
| 内核 | 32 位 zImage（4.9.190） | ✅ 公开源码可编 64 位：`k61v1_64_bsp_defconfig` + 本机 `base.dtb` |
| LK | **32 位，A64 特征 0 处** | ❌ 闭源无源码；只能借同芯片 64 位机型（`full_k61v1_64_bsp`：Blackview BV5900 / RAVOZ Z4 / Digit Play 1 / Ulefone Note 7P / Duoqin F21 Pro）的 lk |
| vendor | 390 个 .so 全 32 位，无 lib64 | ❌ 无解，只能整机移植别人的 64 位 vendor |
| 结论 | 方案 A 只换内核 = 收益≈0；方案 B 整机移植 = 唯一能上 A14/15 的路，风险高但可救砖 | 尚未动手 |

**下一步的第一块多米诺**（1 小时可验证）：把供体 64 位 `lk.bin` 写进 lk 分区，看 ATF 日志打 `AArch32` 还是 AArch64，判断位宽开关在 LK 镜像头还是 preloader 的 boot_arg。

---

## 8. 待办 / 需要盯的点

1. **【新发现，建议马上处理】** 昨天删 `locksettings.db` 时把 `lock_screen_lock_after_timeout` 一起重置成了 `null`（默认 5000 ms）。如果"熄屏 5 秒又自动亮"的循环复发，就是这个原因：
   ```
   settings put secure lock_screen_lock_after_timeout 86400000
   ```
2. 熄屏亮屏的循环会让屏幕 6/7 时间常亮，**放电测试数据全部失真**，要重测需先清 `/data/local/tmp/battlog.txt`。
3. 这块换过的电芯内阻 217~280 mΩ（正常 40~80），低电量+大电流会压降关机 → 看起来像"突然重启"，别误判成系统问题。
4. 64 位方向待你拍板：拿供体固件 → 我先做 LK 镜像头对比（不刷机）→ 再决定只换内核还是整机移植。
5. `load average 22` 是 MTK 内核线程常态（D 状态多），不是卡死。

---

## 9. 操作速查

```bash
# 连接 / 提权
adb devices && adb root && adb shell

# 进 fastboot（设备关机后）：按住 音量下 + 电源
fastboot devices
fastboot --disable-verity --disable-verification flash vbmeta vbmeta.img
fastboot flash boot boot.img          # 救砖主力，boot 分区起始 0x1C800000

# 刷 GSI（super 元数据已修好，可直接用）
fastboot resize-logical-partition system 1905778688
fastboot flash system lineage-xx-a64_bvN.img

# 只读检查
adb shell getprop ro.boot.verifiedbootstate   # orange = 已解锁
adb shell uname -m                             # armv7l = 32 位
python D:/ydt1_work/scan_bits.py               # 判断任意 lk/内核是 32 还是 64 位

# 刷机匣（GeekFlashTool）路径：使用自定义地址 → 添加地址块 → 绑定文件 → 刷入
#   lk   : 地址 0x1C600000  大小 0x100000
#   boot : 地址 0x1C800000  大小 0x2000000
#   super: 地址 0x20800000  大小 0x89504C00
```

---

*文档由 AI 根据 `D:/IMG/ydt1` 读回镜像、设备在线快照、以及历史工作记录整理。所有"实测"结论均可用文中脚本复现。*
