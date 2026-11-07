# 方案 B / C 执行手册（含验证体系与 CI 搭建）

> 配套：`YDT1_总览.md`、`64位可行性分析.md`
> 本文档的三个结论都建立在**今天新挖到的实测证据**上，先看第 0 节。

---

## 0. 三条新证据（改变了原判断）

**证据 1｜expdb 是可靠的"黑屏也能看死在哪"通道（已实测）**
`expdb` 分区里存着每次启动的完整 RAM log：preloader → LK → ATF → 内核，环形保留 3 份。
刚在本机导出 20 MB 验证，能看到 `[ATF](0)[2.196751]NOTICE: Kernel is 32Bit` 这类逐字日志。
→ **以后任何刷机实验失败，都不再是"黑屏不知道为啥"，而是"再开一次机、读 expdb"。**
工具：`tools/expdb_log.py`

**证据 2｜ATF 的内核位宽是"跳之前现场看镜像头"判定的**
日志里 `save kernel info` → `Kernel is 32Bit` → `pc=0x40008000` 三行紧挨着。
说明 ATF 不是在启动早期被 preloader 定死"我只能跑 32 位内核"，而是**在交接瞬间检查入口处的
镜像头**。因此 32 位 LK 不一定锁死 64 位内核 —— 这条原判断要重新验。

**证据 3｜`bootopt=64S3,32S1,32S1` 就写在 boot.img 的 cmdline 里（偏移 0x40）**
即"EL3=64 位、EL1=32 位"这个声明是**镜像里的一个字符串**，不是熔丝。
同时本机 boot.img 的 `kernel_addr = 0x40008000`（32 位 zImage 地址），
而 AArch64 Image **必须**装在 2 MiB 对齐地址（MTK 惯例 `0x40080000`）。
→ **上次 4.19 64 位内核刷进去 bootloop，最可能就是地址没改：ATF 在 0x40008000 读不到
`ARM\x64` magic，判成 32 位，直接跑飞。** 不是"LK 引导不了 64 位内核"。

**证据 4｜ATF 退出 EL3 时打印的是 `Entry point address = 0x48000000` + `SPSR = 0x1d3`**
（启动 0.045 秒处，早于 LK 运行）。`0x1d3` 解码 = AArch32 / SVC 模式 / ARM 态 / 中断屏蔽，
即 **ATF 是以 32 位模式跳进 LK 的**。
又：`0x1d3` 这个值在 preloader（217 KB）和 tee1.img（113 KB 有效段）里**都没有对应字面量**
（已逐字节扫过，0 处命中）→ 它是 preloader 用代码/结构体算出来塞进 boot_arg 的，
不是一处能 4 字节改掉的常量。

**这条把方案 C 判了。** 但注意它和证据 2 是两条独立的路：

| 谁决定位宽 | 决定时间 | 当前值 | 能不能改 |
|---|---|---|---|
| **BL33（LK）** | preloader → ATF 交接时（0.045 s） | AArch32 | 要逆向 preloader 的 boot_arg 构造，难 |
| **内核** | LK → ATF 的 SMC 时（2.19 s），现场读镜像头 | 32Bit | 换个 64 位 Image 就能变，容易 |

**所以：方案 A（32 位 LK + 64 位内核）依然有戏，值得先做 G1；方案 C 基本不通。**

这四条把"第一块多米诺"的成本从「借 64 位 lk 刷机」降到「重打包一个 boot.img」。

---

## 1. 方案 B｜整机 64 位（本质：移植同芯片 ROM）

### 1.1 到底要动哪些分区

| 分区 | 来源 | 必要性 | 风险 |
|---|---|---|---|
| preloader | **保持本机** | — | 动=可能变砖头，EMI/DRAM 参数在里面 |
| lk | 供体（必须是 AArch64） | 若 G1 证明不需要则跳过 | 中，可救 |
| tee1/tee2（ATF） | 供体 | 供体内核+vendor 可能要求配套 ATF | 中高，可能变砖但 BROM 可救 |
| boot | 自编 64 位 Image + **供体 ramdisk**（含 fstab/first-stage init） | 必须 | 低 |
| dtbo | 本机 `base.dtb` 抽取的板级 overlay，按供体内核 DT 结构改写 | 必须 | 低 |
| super（system/vendor/product） | 供体整套（重打包成我们的尺寸） | 必须 | 中 |
| md1img（基带） | 优先本机；不行再换供体 | 看需求 | 低（本机是学习机，可无基带） |
| nvram / nvdata / protect1/2 | **绝对保持本机** | — | 换了丢 IMEI/WiFi 校准 |
| vbmeta | 重做或继续 `--disable-verity --disable-verification` | 必须 | 低 |

### 1.2 三条硬约束（这才是方案 B 的真难点）

1. **super 只有 2.15 GiB，且 liblp 元数据是上一任改过的那份。**
   供体的 super 通常 4–6 GiB，直刷必失败。两条路：
   - **B1 扩 super**：缩小 userdata → 重写 GPT → 扩 super 分区 → 再刷。要动 GPT，风险中高。
   - **B2 重打包（推荐）**：抽供体的 `system.img / vendor.img / product.img`，
     用 `lpmake` 按我们的 2.15 GiB 重组 super（必要时删 product、裁 system）。
     这是 AOSP 标准工具链，可控。
2. **内核与 vendor 的 `.ko` 强绑定。** vendor 里的内核模块带 `vermagic`，必须和内核版本
   逐字匹配。所以**内核和 vendor 必须成对取自同一台供体**，不能混搭。
3. **DT 必须自己接。** 供体内核的 DTS 描述的是它自己的板子（触摸 i2c 地址、camera 供电
   gpio、charger 参数全不同）。`base.dtb` 只是"我们的硬件接线图"，要往供体内核的
   `k61v1_64_bsp.dts` 里合并节点。**这是方案 B 里唯一无法批量自动化的工作量。**

### 1.3 供体选型（决定难度）

| 供体 | Android | 内核 | 优点 | 缺点 |
|---|---|---|---|---|
| Duoqin F21 Pro | 11 | 4.19 arm64 | 内核/DT 最新，社区有维护 | 4.19 与本机 4.9 差异大，驱动要重对齐 |
| Ulefone Note 7P | 9 | 4.9 arm64 | 内核代际最接近本机 | vendor 太老（VNDK 28），上 A14 GSI 会被卡 |
| Blackview BV5900 / RAVOZ Z4 | 9 | 4.9 arm64 | 存量多、dump 好找 | 同上 |

**要上 A14/A15 GSI，只能选 F21 Pro 这条线**（vendor 太老的话新 GSI 直接拒绝启动）。

### 1.4 成功率与 ROI（说实话）

- 能亮屏进系统：**约 60%**
- 外设全好（触摸/显示/音频/WiFi/充电/相机）：**< 20%**
- 能稳定日常用：**更低**
- 而且 2 GB RAM 跑 arm64 A14 GSI 会更吃紧 —— **方案 B 的收益不是"更快"，是"能装只发
  arm64 的新东西"**。如果你的目标是"折腾明白"，值得；如果是"当生产力"，不值。

---

## 2. 方案 C｜自写 64 位 bootloader

### 2.1 LK 在引导链里到底干什么

| 职责 | 是否必须由我们实现 |
|---|---|
| 时钟/PMIC/UART/USB/**eMMC** 初始化 | preloader 已做大半，需要补 eMMC 与 UART |
| 读 GPT、定位 boot 分区 | ✅ 必做（~200 行） |
| AVB/SBC 校验 | ❌ 已解锁，可跳过 |
| 解 boot.img、拷内核到 0x40080000、传 DTB/ATAG | ✅ 必做（~400 行） |
| fastboot / 充电图标 / 音量键菜单 | 可砍到极简 |
| 最后 SMC 进 EL3，由 ATF 跳内核 | ✅ 必做（这就是下面那个生死问题） |

### 2.2 真正的门槛：BL33 的位宽由谁决定 —— 已判定

**结论：由 preloader 传给 ATF 的 boot_arg 决定，ATF 只是把它打印出来。方案 C 的门槛不在
"能不能写出 64 位 LK"，而在"preloader 愿不愿意以 AArch64 交棒"。**

证据链：
1. 启动 0.045 s，ATF 打印 `Preparing for EL3 exit to normal world` / `Entry point address = 0x48000000` /
   `SPSR = 0x1d3` —— 此刻 LK 还没跑，boot.img 还没被读，所以这个值只能来自 preloader。
2. `0x1d3`（AArch32 SVC）在 preloader 二进制里**没有字面量**，说明不是"一处常量写死"，
   而是由 preloader 的启动参数结构/计算逻辑生成 → 想改就得真逆向那段代码，
   而且要保证改了之后 preloader 还能正常初始化 DRAM（改了就没救）。
3. 换供体 64 位 LK **不会**改变这条：SPSR 是 preloader 给的，供体 LK 只会得到同样的
   `0x1d3`，然后以 AArch32 执行 AArch64 指令 → 秒崩。这也解释了为什么"借 lk"这条路
   在原文档里被标为"第一块多米诺"，其实它连门都进不去。

**除非**同时满足两件事，方案 C 才有理论可能：
- 逆向 preloader，把 boot_arg 里 BL33 的 SPSR 从 `0x1d3` 改成 `0x3c5`（AArch64 EL1h）；
- 同时准备一份真正的 AArch64 BL33。
而改 preloader 的代价是：EMI/DRAM 参数在同一个文件里，改错就是"连 BROM 都进不去，
只能拆机短接"。**风险/收益严重不成比例，这是本文档不建议方案 C 的根本原因。**

### 2.3 MVP 不是"重写 LK"，是"最小 BL33"

真要试，别想着移植整个 LK（display/charging/fastboot 全要）。最小可引导 BL33：
`eMMC 读 → 解析 boot.img → memcpy 到 0x40080000 → 组 FDT → SMC 进 EL3`。
代码量 500–1500 行，2–4 周能出"能开机"的版本。但要先过 §2.2 那道门。

### 2.4 结论

**不建议。** 工作量以月计，且成败取决于一段闭源二进制的内部实现。
它的唯一价值是"如果 B 也失败，C 是最后的理论出口"。

---

## 3. 验证体系｜五个闸门

原则：**每一关只动一个变量，每一关都有一步回滚，每一关都用 expdb 取证。**

| 闸门 | 动作 | PASS 判据 | FAIL 含义 | 回滚 |
|---|---|---|---|---|
| **G0 静态** | 只读分析，不刷机 | 供体 lk 是 AArch64；两边 bootopt / kernel_addr 差异明白 | 供体包不对，换一个 | 无 |
| **G1 换 boot** | 64 位 Image + `kernel_addr=0x40080000` 重打包刷入 | expdb 出现 `Kernel is 64Bit`、`pc=0x40080000`，内核日志滚到 init | 仍打 32Bit → 位宽不由镜像头决定，回到 §2.2 | `fastboot flash boot` 原厂 |
| **G2 换 lk**（**已被证据 4 预判为无用，可跳过**） | 供体 lk 写入 lk 分区 | 按 §2.2，供体 LK 会收到同样的 `SPSR=0x1d3` 被当 32 位执行 → 预计黑屏。此关只用于"验证推断"，不再作为前进路径 | 黑屏 = 推断成立 | 刷回 `lk.img` |
| **G3 方案 A 终点** | G1+G2 同时成立 | `uname -m=aarch64`，系统能起 | 说明 64 位内核与 32 位 vendor 冲突 | 逐个回滚 |
| **G4 方案 B** | 整套 vendor 移植 | 能进桌面、外设冒烟通过 | — | 分区级回滚矩阵 |

### 3.1 64 位判定四件套（缺一不可）

```bash
uname -m                                  # aarch64 ?
cat /proc/cpuinfo | grep -i architecture  # 8 ?
getprop ro.product.cpu.abilist64          # 空 = 用户态还是 32 位
ls /vendor/lib64 2>/dev/null | wc -l      # 0 = vendor 还是 32 位
```
**只有前两条变 = 方案 A；四条全变才算方案 B。**

### 3.2 每次刷机后的标准动作

```bash
python tools/expdb_log.py            # 拉 expdb，看这次死在哪
adb shell dumpsys battery | grep -E 'level|health'
adb shell "logcat -d -b all | grep -iE 'fatal|panic|denied' | tail -30"
```

### 3.3 功能冒烟清单（G4 用）

WiFi 连接 / 蓝牙 / 外放 / 耳机 / 触摸五点 / 亮度调节 / 前后摄 / 充电与电量计 /
自动旋转 / 温度 / 关机充电图标 / 深睡唤醒。

---

## 4. GitHub Actions 搭建

### 4.1 先说清楚它适合干什么

- ✅ 适合：**编内核**（可复现、不依赖你那台 192.168.1.12、随时重跑）
- ❌ 不适合：打整包 ROM（源码 40 GB+、需要 repo 同步、免费 runner 磁盘不够）
- 现实：你已经有编译盒子，CI 的价值是"**换机器也能编、每次结果一致**"，不是提速。

### 4.2 仓库结构（把 `D:/ydt1_work` 变成仓库即可）

```
your-repo/
├─ .github/workflows/kernel-build.yml   ← 已写好，直接放进去
├─ tools/
│   ├─ repack_boot.py                   ← 已写好
│   ├─ expdb_log.py
│   └─ img_inspect.py
├─ patches/                             ← 可选，*.patch 自动应用
└─ stock/boot.img                       ← 可选，放了就能自动出 boot64.img
```

### 4.3 workflow 关键点（`kernel-build.yml` 里都有注释）

1. **`jlumbroso/free-disk-space`**：默认 runner 只有 14 GB，MTK 4.9 源码 + out 要 20 GB，不腾必然失败。
2. **`actions/cache` 缓存 `kernel/` 目录**：源码 1.5 GB，首次 clone 6 分钟，之后秒级。
3. **工具链用 AOSP gcc 4.9**（`LineageOS/android_prebuilts_gcc_..._aarch64-linux-android-4.9`，已验证仓库存在）。用 Ubuntu 自带的 gcc 11 编 4.9 内核会遇到 `-fcommon`/`-Werror` 一堆报错。
4. **产物必须自检**：读 `Image` 偏移 0x38 是不是 `ARM\x64`，不是就别拿去刷（workflow 里已加）。
5. **打包 boot 时强制 `--kernel-addr 0x40080000`**，这是 §0 证据 3 的落地点。

### 4.4 常见坑

- `make dtbs` 在 4.9 上偶发 `dtc` 段错误 → 换 `DTC_EXT` 或跳过 dtbo。
- MTK 4.9 的 `mkdtimg` 不在源码里，dtbo 要单独用 AOSP 的 `mkdtimg`。
- 免费 runner 单 job 上限 6 小时，编内核通常 25–50 分钟，够用。
- 别把 `stock/boot.img`（32 MB）反复提交，会撑大仓库；放 Release 用 curl 下更好。

---

## 5. 凭据怎么给（重要）

**不要给密码。** 三个理由：
1. 聊天记录会留存，密码等于永久泄露；
2. GitHub 开了 2FA 的话，光有密码也登不进去，给了也没用；
3. 一个密码能改的东西远多于"跑一次 CI"需要的东西。

按推荐顺序：

| 方式 | 我能做什么 | 你暴露什么 | 撤销 |
|---|---|---|---|
| **A. 我只写文件，你点 Run**（推荐） | 全部代码/配置 | 零 | — |
| **B. Deploy key（SSH，单仓库、只写）** | 能 push 代码、触发 Actions | 只能写一个仓库，读不到别的 | 仓库 Settings 一键删 |
| **C. Fine-grained PAT（单仓库、Contents 读写、90 天）** | 同上，走 HTTPS | 同上，但 token 是明文串 | 到期自动失效 |

真要自动化，走 B：`ssh-keygen -t ed25519` → 公钥加到仓库 Deploy keys（勾 Allow write）
→ 私钥留在你本地 → 告诉我用它就行，我全程看不到你的账号密码。

---

## 6. 回滚矩阵（打印出来贴桌上）

| 分区 | 回滚镜像 | 地址 | 大小 | MD5 |
|---|---|---|---|---|
| boot | `D:/IMG/ydt1/.../boot.img` | 0x1C800000 | 0x2000000 | `b7ebe7327702a45c125e5f77bf1de3bc` |
| lk | `lk.img` | 0x1C600000 | 0x100000 | `c509d232be1e60a97136ea338221e9c2` |
| tee1 | `tee1.img` | 0x1F800000 | 0x500000 | `b366da5c45e555a7a51c98649c97544c` |
| vbmeta | `vbmeta.img` | 0xA9D04C00 | 0xF42400 | — |
| super 头 | `super_patched.bin` | 0x20800000 | 256 KB | `27700997e9db0a3efdcec3fd00742949` |

```bash
fastboot flash boot  backup/boot.img      # 90% 的情况这一条就够了
fastboot flash lk    D:/IMG/ydt1/.../lk.img
# 连 fastboot 都进不去 → 刷机匣 BROM 直写（走 MTK DA，绕过 bootloader）
```

---

## 7. 建议的下一步（按性价比排序）

1. **G1（半天，0 供体依赖）**：编 64 位 Image → `tools/repack_boot.py --kernel-addr 0x40080000`
   重打包 → 刷 boot → 读 expdb。
   这一步同时决定三件事：32 位 LK 能不能带 64 位内核 / 方案 A 通不通 / 方案 B 要不要动 lk。
   **这是目前唯一值得做的实验。**
2. **G0（1 小时）**：下 Ulefone Note 7P 或 F21 Pro dump，`tools/img_inspect.py diff` 比
   lk 头 + bootopt + kernel_addr 三处差异。
3. G2（换 lk）已被证据 4 预判为无用，**跳过**，省一轮刷机风险。
4. 方案 C 不用再评估 —— 门在闭源 preloader，且没有可打的常量，性价比为零。
