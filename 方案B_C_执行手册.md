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
反汇编进一步发现：`0x1d3` 在整份 ATF 里只出现一次，是一条 `mov w0, #0x1d3`（偏移 `0x276C`），
所以这是一个**可能被 4 字节改掉的常量** —— 但静态分析到此为止，它到底是不是 SPSR 的来源
无法确认，必须实测（见 §2.2 的 L2 实验）。
**注意**：早前"preloader 里没有该字面量所以开关在 preloader"的推论**不成立**，已撤回。

**证据 4 与证据 2 是两条独立的路**：

| 谁决定位宽 | 决定时间 | 当前值 | 能不能改 |
|---|---|---|---|
| **BL33（LK）** | preloader → ATF 交接时（0.045 s） | AArch32 | 未知在哪一层，L2 实验可判 |
| **内核** | LK → ATF 的 SMC 时（2.19 s），现场读镜像头 | 32Bit | 换个 64 位 Image 就能变，容易 |

**所以：方案 A（32 位 LK + 64 位内核）依然有戏，先做 G1；方案 C 悬而未决，用 L2 判。**

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

### 2.2 真正的门槛：BL33 的位宽由谁决定 —— **尚未判定，但有一个 4 字节的实验能判**

**已确定的事实**：启动 0.045 s，ATF 打印 `Preparing for EL3 exit to normal world` /
`Entry point address = 0x48000000` / `SPSR = 0x1d3`。`0x1d3` 解码 = AArch32 / SVC / ARM 态 /
中断屏蔽 —— **ATF 确实是以 32 位模式跳进 LK 的。** 这一刻 LK 还没跑、boot.img 还没读。

**尚未确定**：这个 SPSR 是"ATF 自己定死的"还是"preloader 传进来的"。

静态分析做到这里就断了：
- `0x1d3` 在整份 ATF（113 KB 有效段）里**只出现一次**，是一条 `mov w0, #0x1d3`，
  位于一个"打印 `[RGU-ATF] SW_WDT` 然后返回"的函数末尾 —— 是 SPSR 还是 WDT 状态码，
  静态层面定不了。
- 打印 `SPSR = 0x%x` 的那三个字符串是通过 MTK 的日志字符串池间接引用的，
  `adrp/add` 线性扫描找不到交叉引用（已试过，0 命中）。
- 早前"preloader 里没有 0x1d3 字面量"这个论据**不成立**：常量可以用 MOVZ/MOVT 拼，
  也可以从结构体读，不能凭"没有字面量"就下结论。

**所以：不是"完全没希望"，是"还差一个判定实验"。** 而且这个实验极便宜：

> **L2 判定实验（改 4 字节，不改 preloader、不改 LK）**
> 1. 把 ATF 里那条 `mov w0, #0x1d3`（文件偏移 `0x276C`）改成 `mov w0, #0x3c5`
>    （`0x3c5` = AArch64 / EL1h / 屏蔽中断，同样是 4 字节，无需改长度）
> 2. 刷 tee1 → 开机 → **不管能不能起来，都读 expdb 看 ATF 打的那行 `SPSR = 0x?`**
> 3. 判读：
>    - 打出 `0x3c5` → **开关在 ATF 里**，方案 C 有门（再配一个 64 位 BL33 即可）
>    - 仍打 `0x1d3` → 那个常量不是 SPSR 来源，开关在 preloader → 这时才算判死
>    - 完全无新日志 → ATF 被校验/校验失败（也是有用信息：说明 tee 不能改）
> 4. 刷回 `tee1.img`（MD5 `b366da5c...`）或走刷机匣 DA 直写
>
> 风险等级：中。tee1 可完整回滚；最坏情况是开不了机，用 BROM/DA 写回 5 MB 分区。

**为什么这条比"借供体 lk"值**：供体 lk 受同样一条 SPSR 支配（如果是 ATF 定的），
换了也只会以 AArch32 跑 AArch64 指令秒崩；而改 ATF 这一条，直接命中了可能的开关本身。

### 2.3 MVP 不是"重写 LK"，是"最小 BL33"

真要试，别想着移植整个 LK（display/charging/fastboot 全要）。最小可引导 BL33：
`eMMC 读 → 解析 boot.img → memcpy 到 0x40080000 → 组 FDT → SMC 进 EL3`。
代码量 500–1500 行，2–4 周能出"能开机"的版本。但要先过 §2.2 那道门。

### 2.4 结论

**不建议。** 工作量以月计，且成败取决于一段闭源二进制的内部实现。
它的唯一价值是"如果 B 也失败，C 是最后的理论出口"。

---

## 3. 验证体系｜五关一探针

原则：**每一关只动一个变量，每一关都有一步回滚，每一关都用 expdb 取证。**

| 闸门 | 动作 | PASS 判据 | FAIL 含义 | 回滚 |
|---|---|---|---|---|
| **G0 静态** | 只读分析，不刷机 | 供体 lk 是 AArch64；两边 bootopt / kernel_addr 差异明白 | 供体包不对，换一个 | 无 |
| **G1 换 boot** | 64 位 Image + `kernel_addr=0x40080000` 重打包刷入 | expdb 出现 `Kernel is 64Bit`、`pc=0x40080000`，内核日志滚到 init | 仍打 32Bit → 内核位宽不由镜像头决定 | `fastboot flash boot` 原厂 |
| **L2 探针（新增，判方案 C）** | ATF 4 字节补丁：`0x276C` 处 `#0x1d3`→`#0x3c5`，只刷 tee1 | expdb 的 `SPSR = 0x3c5` | 仍 `0x1d3` = 开关在 preloader，C 判死；无日志 = ATF 被校验 | 刷回 `tee1.img` / DA |
| **G2 换 lk**（**L2 之前做没意义**） | 供体 lk 写入 lk 分区 | 只在 L2 证明"开关在 ATF"后才有价值 | 黑屏 = 受 SPSR 支配，符合预期 | 刷回 `lk.img` |
| **G3 方案 A 终点** | G1 成立 | `uname -m=aarch64`，系统能起 | 64 位内核与 32 位 vendor 冲突 | 逐个回滚 |
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
   **风险最低（只动 boot），应该先做。**
2. **L2 探针（1 小时）**：ATF 4 字节补丁 + 只刷 tee1 + 读 expdb 的 `SPSR = 0x?`。
   这是**唯一能判定方案 C 生死的实验**，比"借供体 lk 去试"便宜一个数量级。
   注意：先做完 G1 再做，避免两个变量同时变。
3. **G0（1 小时）**：下 Ulefone Note 7P 或 F21 Pro dump，`tools/img_inspect.py diff` 比
   lk 头 + bootopt + kernel_addr 三处差异。
4. G2（换 lk）→ 只有 L2 打出 `0x3c5` 之后才值得做。
5. 方案 C 的真正开工前提：L2 打出 `0x3c5`（开关在 ATF）**且** 弄到/写出一个 AArch64 BL33。
   到那一步再算工作量（最小 BL33 约 500–1500 行、2–4 周）。
