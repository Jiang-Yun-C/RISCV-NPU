# T27 CoreMark：可重建的 O2/O3 对照与正式测量入口

2026-10-28 选题一增补：新增显式编译调优、双种子正式记录配对和流水线观测。
本页的普通 O2/O3 默认行为保留；新的测量证据位于包根目录
`verification/competition_v2/`，不是新实板成绩。

本目录提供当前 T09/RV32IMF CPU 的独立 CoreMark 程序。使用现有板端启动文件、
`0xb4000000` DDR 程序区和 `0x20000` 的 64 KiB 片上栈；不改 CPU RTL。
`build_coremark.py` 默认只打印计划，加 `--build` 才生成 ELF、原始 bin、map 和构建凭据。
脚本只在本地构建，不包含下载到 FPGA、写 SD/Flash 或操作串口的功能。

## 已实现的改动

- `mcycleh/mcycle/mcycleh` 稳定读取 64 位周期，能跨过 RV32 低字回绕。
- 正式模式显式给出真实频率；默认 T27 构建为 125 MHz。时间先转换为 double 再相除，
  不再把小数秒截成整数。旧 T21 调试调用默认仍为 100 MHz，保留原短测试提示。
- 性能种子为 `0,0,0x66`，校验种子为 `0x3415,0x3415,0x66`。
- 正式模式固定 2000 B 总工作集、单上下文、浮点报告；不能使用合成的主机测试计时器。
- 新报告器直接输出字符，支持上游实际使用的格式，不依赖缺失的 `ecvtbuf/fcvtbuf`、
  libc/libm 或 1 KiB 格式化缓冲。原 `ee_printf.c` 保留给历史 T21 构建。
- O2/O3 使用相同算法、ISA/ABI、种子和存储布局。LTO 是显式独立实验；没有默认启用
  `-Ofast`、fast-math 或浮点融合。
- 原始 `CM_TICKS high=... low=...` 记录完整周期。上游 `core_main.c` 的 `Total ticks`
  在 RV32 只输出低 32 位，校验器会同时核对两者。

CoreMark 的整数内核不会因这里的浮点报告器而使用 FPU 计算；报告工作在计时区间之外。
正式测量前会等 UART 前导文字发完，避免把最后一个前导字符的线路等待记进计时区间。

## 上游来源与完整性

`upstream/` 来自 [EEMBC/CoreMark](https://github.com/eembc/coremark)，固定提交为
`1f483d5b8316753a742cbf5590caf5bd0a4e4777`。五个算法 C 文件和 `coremark.h` 均为官方原样。
`UPSTREAM.json` 保存来源 URL、长度、SHA256 和从官方 Git tree API 核对的 Git blob SHA1；
每次构建重新校验全部文件。

上游自带的 `coremark.md5` 也原样保留：五个算法 C 文件均与它一致，但该提交的
`coremark.h` 对应条目已经陈旧。不要把这一旧 MD5 条目覆盖到真实头文件上；头文件身份
以固定提交的 Git blob 和 SHA256 为准。许可证见 `upstream/LICENSE.md`。

## 构建短测对照

在 `source/` 目录运行，`--cc` 指向实际可用的 RV32 GCC。编译器需支持
`-march=rv32imf_zicsr_zifencei -mabi=ilp32f`，并选择相同 ABI 的 libgcc。
不要仅凭可执行文件名字含 `riscv64` 或 `riscv32` 推断 multilib 是否正确。

```bash
python3 scripts/build_coremark.py --build --cc /path/to/riscv32-unknown-elf-gcc \
  --opt O2 --mode debug --iterations 10 --output ../coremark-runs/o2-debug-10
python3 scripts/build_coremark.py --build --cc /path/to/riscv32-unknown-elf-gcc \
  --opt O3 --mode debug --iterations 10 --output ../coremark-runs/o3-debug-10
python3 scripts/build_coremark.py --build --cc /path/to/riscv32-unknown-elf-gcc \
  --opt O3 --lto --mode debug --iterations 10 --output ../coremark-runs/o3-lto-debug-10
python3 scripts/build_coremark.py --build --cc /path/to/riscv32-unknown-elf-gcc \
  --opt O3 --mode debug-validation --iterations 10 --output ../coremark-runs/o3-validation-10
```

已有输出目录会被拒绝，防止覆写旧证据或在编译失败后误用残留二进制。
构建凭据记录所有算法/移植/启动/链接输入的 SHA256、编译器版本、编译器或包装器身份、
实际 cc1/libgcc 身份、完整参数、构建前后输入一致性、ELF/bin/map 身份。
成功构建的状态是 `BUILT_NOT_EXECUTED`，不会自动产生分数。

O2/O3 对照必须使用同一 CPU RTL、时钟和存储模型；10 轮比单轮更能减少冷 cache 的比例。
真实 RTL 的短测试可以报告周期差与 CRC，但不足 10 秒时不能称为正式 CoreMark 分数。
模拟器墙钟时间也不能代替 CPU 周期。

## 正式性能/校验两组

使用同一编译器和同一个优化组合，各自构建性能与校验程序。省略 `--iterations` 时，
未修改的上游框架会自动选取迭代数；正式校验器仍独立要求实际计时不少于 10 秒。

```bash
python3 scripts/build_coremark.py --build --cc /path/to/riscv32-unknown-elf-gcc \
  --opt O3 --mode performance --hz 125000000 --output ../coremark-runs/o3-performance
python3 scripts/build_coremark.py --build --cc /path/to/riscv32-unknown-elf-gcc \
  --opt O3 --mode validation --hz 125000000 --output ../coremark-runs/o3-validation
```

这些输出是独立基准程序；加载必须沿用项目的测试镜像装载与身份核对流程，不能当作
原有模型应用直接覆盖。当前软件构建也不改变已认证 loader 接受的镜像身份。

保存各自完整 UART 原文后校验：

```bash
python3 scripts/build_coremark.py --validate-log performance-uart.txt \
  --mode performance --hz 125000000
python3 scripts/build_coremark.py --validate-log validation-uart.txt \
  --mode validation --hz 125000000
```

校验器核对种子与工作集、官方 CRC、原始 64 位计数、低字输出、小数秒、迭代速率、
完成标记和错误输出。短测可加 `--allow-short`，但对应 `coremark` 字段为空。
单日志通过只会给出 `formal_run_log_valid`；`release_qualified` 始终为 false。
正式发布还需要匹配两组的构建/二进制身份，独立确认板上 CPU 频率，并记录代码、数据、
cache 频率和 memory:core、cache:core 时钟比例。CoreMark/MHz 不能脱离这些存储条件。
CoreMark/LUT 还需要明确 CPU 单独资源与整机资源的分母，当前脚本不估算该值。

新增 `scripts/report_coremark_competition.py` 可配对两组正式原始记录与构建产物，
检查时钟依据、CPU/整机资源归属并生成一致性报告。用法及空白实测模板见
`docs/spec/coremark-competition.md`。一致性通过不代表工具独立鉴定了板端来源或比赛认可。

可选 `--memory ddr` 将标准的工作集分配方式改为 `MEM_STATIC`，工作集落在 DDR，供存储
敏感性对照；默认 `--memory stack` 使用已经存在的片上栈。两组存储条件应分别标明，
不能把两者之差描述成当前生产应用新获得的“栈搬迁收益”。

## 可选编译调优与流水线证据

新增 `--tuning none|unroll|unroll-no-if-conversion`。默认 `none` 不改变原有 O2/O3
编译命令；其余两项只与 O3 组合，并完整写入 UART 的 Compiler flags 和构建凭据。
官方算法、种子、工作集、频率与浮点规则保持相同。没有按算法函数单独设定参数。

本次 GCC 12.2、原 T09 RTL、行为 AXI 模型、10 轮测试中，
`unroll-no-if-conversion` 的性能/校验周期分别为 5,951,817 / 5,967,761；
普通 O3 为 6,032,017 / 6,056,521。该参数组合为
`-funroll-loops -fno-if-conversion -fno-if-conversion2`，基准程序加载镜像
32,432 → 40,144 B。由于代码体积和取指流量增加，这是需要在真实工具链与板卡上
继续对照的可选项，不自动用于完整模型应用。正式 CoreMark 分数仍为空。

```bash
python3 scripts/build_coremark.py --build --cc /path/to/riscv32-unknown-elf-gcc \
  --opt O3 --tuning unroll-no-if-conversion --mode performance \
  --output ../coremark-runs/tuned-performance
python3 scripts/build_coremark.py --build --cc /path/to/riscv32-unknown-elf-gcc \
  --opt O3 --tuning unroll-no-if-conversion --mode validation \
  --output ../coremark-runs/tuned-validation
```

两套正式构建必须使用完全相同的调优组合。`tests/cpu_pipeline/` 提供基于真实
执行的五级流水线/AXI 观测、有限窗口 CSV/VCD 和可选硬件 ILA 探针映射。
仿真波形不替代赛题要求的实板 ILA 捕获；调试探针插入后需要单独复验时序和资源。

## 回归测试

```bash
python3 -m unittest discover -s tests/coremark -v
```

测试覆盖高低字间回绕重读、多次低字回绕、64 位差值、1 周期小数时间、正确种子、
格式输出、禁止合成时钟冒充正式模式、官方算法在 O2/O3 下的两套 CRC、源文件篡改、
正式时长边界、错误频率/CRC/速率、缺失/混合日志。主机测试的计时为明确标识的合成夹具，
只校验行为，不能用于推断本项目 CPU 性能。
