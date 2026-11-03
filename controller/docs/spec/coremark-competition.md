# 选题一：CoreMark 比赛测量与证据配对

本文对应上传的《全国大学生嵌入式芯片与系统设计竞赛 2026 选题指南（紫光同创）》
选题一，PDF 第 10–11 页、正文第 8–9 页。相关要求包括 CoreMark v1.0、
CoreMark/MHz、满足时序约束的工作频率、CoreMark/LUT，以及至少 10 秒的测试。
指南另要求用 ILA 分析 CoreMark 算法执行波形；波形分析由独立的 CPU 观察工具提供，
不会被本报告器的“日志一致”结论代替。

## 本轮补上的能力

`scripts/report_coremark_competition.py` 把正式性能种子与校验种子的两次测试配成一份报告：

1. 同时核对两套官方 CRC、正的实际迭代次数，以及两次测试均达到 10 秒。
2. 将 UART 原文、采集记录、实际装载的 bin、ELF、构建凭据逐项用 SHA256 关联。
3. 要求两组使用相同 CPU/位流/存储配置、相同工具链与优化参数、相同源码身份。
   只允许性能/校验种子与迭代次数不同；新增的 `--tuning` 等编译选项也会进入配对检查。
4. 支持同位流的输入时钟/PLL 配置依据，以及独立参考计数实测两种频率口径，记录
   I/D Cache、内存接口与 CPU 的时钟比例；配置频率不会标成实测频率。
5. 分别计算 CPU 层级、整 SoC 层级的 CoreMark/LUT，并保留实现阶段和 LUT 定义。
6. 若提供匹配的 post-route 摘要，检查该工作点的 setup/hold 与约束覆盖；不由 WNS 推算更高 Fmax。

输入声明为仿真、合成计时、旧短调试，或不足 10 秒时，脚本拒绝输出通过报告。
已有报告文件也会被拒绝覆写。

**通过状态为 `EVIDENCE_CONSISTENT`，表示文件身份和记录内容一致。** 程序无法独立判断
任意用户提供的文件是否真的来自板卡或测量仪器，因此始终输出
`competition_approval: false` 和 `independently_authenticated_board_origin: false`。
评委认可、仪器溯源与现场演示仍由实际证据和评审确定。这些字段不能手工改成“已经认证”。

## 1. 构建两组正式程序

在 `source/` 下，使用同一套实际工具链和选定优化组合，例如：

```bash
python3 scripts/build_coremark.py --build --cc /path/to/riscv32-unknown-elf-gcc \
  --opt O3 --mode performance --hz 125000000 --output ../runs/performance
python3 scripts/build_coremark.py --build --cc /path/to/riscv32-unknown-elf-gcc \
  --opt O3 --mode validation --hz 125000000 --output ../runs/validation
```

若采用额外 tuning/LTO，两条命令必须使用相同选项，并保留对应正确性与周期证据。
`--iterations 0` 表示让未修改的上游框架先估计并选取轮数；最终 UART 必须记录正的
实际 `Iterations`，且实测时间满足要求。若赛方要求在正式演示前固定轮数，可用预跑得到
的轮数重新编译 `--iterations N`，再执行并保存正式原文。不要以单轮/十轮短测代替正式结果。

CoreMark 是独立测试程序，加载流程仍需遵循项目既有的镜像身份与测试装载流程。
本脚本不会改变已认证 loader 的允许镜像，也不自动操作 JTAG、UART、SD 或 Flash。

## 2. 收集一个完整证据目录

所有文件引用均相对 `session.json` 所在目录，路径与 SHA256 必须准确，目录外路径被拒绝。

| 子目录 | 原始材料 |
|---|---|
| `hardware/` | 实际运行的位流文件、对应 CPU RTL；记录板卡身份、SoC top 与 CPU 实例层级 |
| `performance/` | 原始 UART、ELF、bin、`BUILD_RECEIPT.json`、该次采集的 `CAPTURE_RECEIPT.json` |
| `validation/` | 校验种子的同类材料，使用独立 run_id |
| `clock/` | 输入时钟与实际PLL/分频配置，或独立参考频率依据与计数CSV；另含Cache/内存时钟关系与时钟记录 |
| `resources/` | CPU 或整 SoC 的原始资源报告，以及带层级/阶段/LUT 定义的记录；缺少某项可留空 |
| `timing/` | 同位流 post-route 原始时序报告及摘要；没有匹配报告时留空 |

生成空模板：

```bash
python3 scripts/report_coremark_competition.py --template > session.json
python3 scripts/report_coremark_competition.py --template --template-kind capture > capture-template.json
python3 scripts/report_coremark_competition.py --template --template-kind clock > clock-template.json
python3 scripts/report_coremark_competition.py --template --template-kind clock-configured > configured-clock-template.json
python3 scripts/report_coremark_competition.py --template --template-kind resource-cpu > cpu-resource-template.json
python3 scripts/report_coremark_competition.py --template --template-kind resource-soc > soc-resource-template.json
python3 scripts/report_coremark_competition.py --template --template-kind timing > timing-template.json
```

模板中的实测值全部为空，不把目标频率、旧资源记录或示例分数自动填成新测量。
文件 SHA256 可用 `sha256sum 文件名` 获取。完成所有子记录后，再将它们的真实文件路径与
SHA256 填入 `session.json`；不要把 JSON 的打印值当作原始测量文件。

## 3. 采集身份和时钟口径

每次采集记录必须包含 `execution_origin="physical_board"`、`synthetic=false`、板卡身份、
位流与 CPU RTL SHA256、时钟/存储配置标识、run_id、采集时间、UART SHA256、实际装载 bin
的 SHA256。只有确实在板上执行时才使用这些声明。构建凭据中的 `executed_on_target=false`
仍是构建时事实；后续板端执行由新的采集记录承接，不修改历史构建凭据。

**赛题没有要求额外搭建独立参考计数器。** 该方法只是本项目可选的强化验证，当前PDS/板卡
流程可选择下面的配置依据方法；两种口径在输出中明确区分。

### 方法A：实际输入时钟与PLL/分频配置

选择 `method="documented_clock_configuration"`，填写板上实际输入时钟的 `input_clock_hz`
与来源依据，以及整个PLL/分频链的 `effective_multiplier`、`effective_divider`：

\[
f_{\mathrm{CPU,configured}}=f_{\mathrm{input}}\frac{M_{\mathrm{effective}}}{D_{\mathrm{effective}}}.
\]

`input_clock_evidence` 指向板卡时钟来源资料或测量，`configuration_evidence` 指向实际
使用的PLL/IP/分频配置，并与该次运行位流身份绑定。单独的SDC/FDC目标频率、WNS、
“希望运行125MHz”的说明不构成完整配置依据。

该方法输出 `frequency_basis="configured"`。若频率不确定度尚无依据，允许
`uncertainty_ppm=null`，此时10秒按配置频率名义值检查，时长依据标成
`configured_nominal_only`；独立实测频率与时长字段保持空值。CoreMark和CoreMark/LUT
进入单独的 `configured_frequency_*` 字段，并在Markdown注明“配置频率名义值”。
这提供可用的比赛报告准备路径，同时避免把配置值冒充仪器实测结果。

### 方法B：独立参考计数（可选）

选择 `method="independent_reference_counter"`。原始 CSV 必须只有一个完整窗口，
列名依次为：

```csv
reference_ticks,core_cycles
```

将实际测到的整数计数作为第二行。程序按

\[
f_{\mathrm{CPU}}=f_{\mathrm{reference}}\,
\frac{\mathrm{core\_cycles}}{\mathrm{reference\_ticks}}
\]

求 CPU Hz。`reference_hz` 必须附带频率依据；`uncertainty_ppm` 应覆盖参考精度、计数窗口
量化和测量方法误差。最短测量时间使用频率上界检查，因此刚好显示 10.000000 秒、但计入
测量不确定度后不足 10 秒的记录会被拒绝。实践中应给正式运行时长留出余量。

两种方法均可给出有依据的不确定度；一旦给出，就按对应频率上界检查时长。独立参考测量
方法必须提供这个误差范围，不能省略后宣称精确测量。

`maximum_clock_deviation_ppm` 明确给出计时器声明频率与所选有依据频率的允许偏差。这是本次
工程测量选择，不是指南给出的额外评分规则。报告会完整保留实际偏差和允许值。

`domains` 要求记录 `icache_to_core`、`dcache_to_core`、`memory_interface_to_core` 的正整数
分子/分母，并附时钟连接依据。内存接口要明确名称，例如 HMIC 用户接口时钟；DDR 数据率
MT/s不能当作接口时钟 Hz。PLL 配置只支持“配置频率”口径；PDS约束目标本身不能替代
实际输入/PLL配置，也不能替代独立频率测量。

## 4. 正确计算三个指标

设性能种子的实际轮数为 \(I\)，64 位周期数为 \(C\)，所选口径的频率为 \(f\) Hz：

\[
\mathrm{CoreMark}=\frac{I f}{C},\qquad
\mathrm{CoreMark/MHz}=\frac{10^6 I}{C},\qquad
\mathrm{CoreMark/LUT}=\frac{I f}{C\,L}.
\]

MHz 的百万倍换算必须明确。CoreMark/MHz由轮数和周期直接计算，频率在代数上约去。
CoreMark与LUT效率则区分独立实测频率折算值和配置频率名义值；未知项不会被自动升级。
用于核对原始UART的声明时钟秒数/速率另列在测试记录中，避免混淆。

CPU 与整 SoC 的 LUT 不能互相替代。资源记录分别指定 `scope="cpu"` 或
`scope="whole_soc"`，并绑定 `hardware.cpu_instance` 或 `hardware.soc_top` 的完整层级。
必须提供 `covers_entire_hierarchy=true`、LUT 正整数、`lut_definition`、工具版本和
`implementation_stage`（synthesis/device_map/post_route）。例如，CLMA LUT 与 CLMS LUT
是否合计必须写清楚；逻辑单元、LUT、DRM 原语个数不是可互换的分母。
指南没有在该段明确 CPU/整机分母的所有细节，报告并列提供两种可追溯口径，不代替评委作最终选择。

匹配的 post-route 时序摘要可以证明提供的记录描述了同一工作点，但**单个通过的频率
不证明最高工作频率**。本工具的 `fmax_hz` 始终保持空值，直至另有真实的频率探索与完整
功能/时序证据。不能用 `1/(周期-WNS)` 填上一个未运行的“Fmax”。

## 5. 导出报告与回归

```bash
python3 scripts/report_coremark_competition.py session.json \
  --output coremark-report.json --markdown coremark-report.md
python3 -m unittest discover -s tests/coremark_competition -v
```

JSON保留所有输入文件身份、配对条件、频率与资源分母；Markdown给出可审阅的指标表。
29项回归用明确标识的临时合成夹具检验判定逻辑，包含两seed配对、跨低字回绕、正式时长、
真实频率/不确定度边界、拒绝仿真/调试/合成时钟、二进制/算法/工具链错配、LUT口径互换、
负时序裕量、文件篡改、防覆写及配置频率与独立实测的区分。正例只证明程序能处理一致的输入，不能证明测试夹具来自板卡。
本轮没有附加新的正式板端分数。
