# T09 流水线观测、有限波形与板上 ILA 接线表

本目录在**原样 T09 RTL**上增加仿真观察，不修改 CPU、缓存、预测器、AXI 时序或 SoC。新增独立的 profiling 仿真器，原 `tests/cpu_rtl/` 的执行器和历史实验保持原样。这里产生的 CSV、VCD 和图片是实际 RTL 运行的采样结果，**不是物理 FPGA ILA 抓图，也不是正式 CoreMark 成绩**。赛题要求的板上 ILA 性能分析仍需上板完成。

## 1. 观测实现与边界

`signals.vlt` 仅用 Verilator 的 `public_flat_rd` 暴露指定内部信号。`pipeline_profile.hpp` 只读取信号，不写 CPU 内部状态。`cpu_profile.cpp` 保留原行为 AXI 存储器，驱动、握手、ROM 跳转和完成条件保持一致；在每个非复位周期的上升沿之前采样。一次运行收集全程序计数，以及一个最多 16,384 周期的连续窗口，默认 1,024 周期、触发前 128 周期。没有全层级、全运行 VCD。

原 CPU 文件 SHA-256：

```text
be3866488f1782aeecf6d52c4a8ea933edd56b937f078fae0ae4f23be29d2008
```

原寄存器初始化文件 SHA-256：

```text
b8b891b81fd1c062082faf97533834198d8a4c4b6867899d6218712132a8ed38
```

运行记录同时绑定 CPU、初始化文件、C++ 执行器、观察头文件、只读信号配置、可执行仿真器、目标 binary、目标 ELF 和原始轨迹的 SHA-256。读取 ELF 符号之前，检查 ELF32/RISC-V/入口地址及全部有文件内容的加载段与 binary 一致，避免用另一个编译版本的函数地址触发。

### 计数语义

| 字段 | 实际定义 | 解释限制 |
|---|---|---|
| `active_cycles` | 非复位采样周期数 | 整个程序，含初始化、参考计算、计时、输出和结束处理 |
| `retired` | `trace_retire = writeBack_arbitration_isFiring` | 以实际写回提交信号计数 |
| `execute_stall_cycles` | `execute.isValid && execute.isStuck` | 不等于所有无提交周期 |
| `conditional_branches` | M 级 firing 且指令 opcode 为 `0x63` | 排除 JAL/JALR，不能用全部跳转作分母 |
| `conditional_mispredicts` | 上一条件与 `T09IBus_decodePrediction_rsp_wasWrong` | 误预测率分母只用条件分支数 |
| `stage_valid/stuck/fire_cycles` | F、D、E、M、W 的有效、有效且阻塞、传递周期 | 各级可同时计数；不能相加当作总周期拆分 |
| `i/d_read_wait_cycles` | 行为模型已有未完成读事务且对应 `RVALID=0` | 观测响应等待，既不是全部 cache miss 数，也不是排他的 CPU 停顿原因 |
| `write_response_wait_cycles` | 已接收写事务最后一拍，尚无 `BVALID` | 与流水线活动及其他等待可重叠 |
| `data_bus_hazard_cycles` | 原 `dBusToAxi4Shared_hazard` 电平 | 包括外部读写顺序限制，不能断言所有 CPU load 都被阻塞 |
| `data_refilling_cycles` | 原 `dataCache_1_io_cpu_execute_refilling` 电平 | 不是根据耗时猜测 miss |
| `pending_write_cycles` | 原 pending-write 计数器非零的周期 | 另记录观察到的最大占用 |
| `execute_load/store_fires` | E 有效、内存操作类型匹配，且 E firing | 执行级事件，不命名为最终退休 load/store 数 |
| `fetch_flush_cycles` | `T09IBus_iBusRsp_flush` 为高的周期 | 电平持续周期，不是“flush 次数” |
| `axi_handshakes/backpressure` | 各通道 `valid && ready` / `valid && !ready` | 读数据按 beat 计，非请求数或字节数 |

这些事件**相互重叠**。不得把等待项相加画成无重叠的 CPI 成分图。全程序 CPI 与 CoreMark `CM_TICKS` 的精确计时区间不同，不能将全程序事件差值直接当作计时核心区间的因果分解。编译版本的打印字符串长度也不同。

F 是实际取指响应路径 `T09IBus_iBusRsp_stages_2` 的观察点，前端另有缓冲结构；这里没有声称 F 是全部取指逻辑的唯一寄存器。F 的 PC 为 `...stages_2_input_payload`，valid 为 input_valid，stuck 为 input_valid 且非 input_ready，fire 为 output_valid 且 output_ready；原 RTL 的组合连接保证该 fire 与 input 握手等价。D/E/M/W 使用同名仲裁与 PC。无效级的 PC 位可以保留旧值，分析必须同时看 valid。

## 2. 复现实验

从源码根目录执行；所有输出路径显式指定且拒绝覆盖既有结果。以下路径由实际环境填写，没有写死某台机器的默认路径。

```sh
python tests/cpu_pipeline/run_profile.py build \
  --directory /path/to/new-profile-simulator \
  --verilator /path/to/verilator \
  --verilator-root /path/to/verilator/share

python tests/cpu_pipeline/run_profile.py run \
  --directory /path/to/new-profile-simulator \
  --binary /path/to/O3/coremark.bin --elf /path/to/O3/coremark.elf \
  --output /path/to/results/O3.json \
  --symbol core_bench_list --trigger mispredict \
  --trace-samples 1024 --pretrigger-samples 128 \
  --read-latency 3 --write-latency 3 \
  --reference-result /path/to/original-uninstrumented-O3.json

python tests/cpu_pipeline/run_profile.py run \
  --directory /path/to/new-profile-simulator \
  --binary /path/to/tuned/coremark.bin --elf /path/to/tuned/coremark.elf \
  --output /path/to/results/tuned.json

python tests/cpu_pipeline/check_profile.py \
  /path/to/results/O3.json /path/to/results/tuned.json \
  --output /path/to/results/COMPARISON.json

MPLCONFIGDIR=/tmp/t09-matplotlib python tests/cpu_pipeline/render_trace.py \
  /path/to/results/tuned.json --output /path/to/results/tuned.png
```

`retire`、`mispredict`、`data-wait` 三种触发都要求对应 PC 位于 ELF 中选定函数的真实地址范围；分别使用 W PC、M 分支 PC、有效 E PC。窗口只保证触发点在该函数内，前触发区及后续窗口可以包含调用者或被调函数。默认选择的是首次匹配，不保证该次调用位于 CoreMark 精确计时区间内。

存储器模型延迟参数 `3` 表示额外等待，AR 后最早第 4 个周期出现 R，写入最后 W 后最早第 4 个周期出现 B；本地 SRAM 使用额外等待 1。模型不是完整 SoC DDR/PHY，也不能拿它的时钟显示比例宣称板上 DDR 延迟。

VCD 是有限的、逐周期采样的选定 RTL 信号。其 1 ns 单位与每周期 10 个逻辑时间单位只用于显示，**不代表测得 100 MHz，也不替代程序报告的名义频率或板上时钟核查**。它不记录一个周期内的组合毛刺。

独立检查器核查：当前源码身份、CPU 完成、官方调试 CRC、64 位周期数、无正式分数、轨迹哈希、连续长度、实际符号触发、逐级 firing 关系、WB 与退休信号一致、条件分支分母、CSV 重计数、VCD 与 CSV 每个字段逐样本一致、原执行器计数与新观察器计数一致。带 `--reference-result` 的运行还要求原有 UART、所有原计数和结束状态逐项完全相等。

## 3. 本次实际观测

两次都是 2000 B 总工作集、10 次迭代、performance seeds、`formal=0`，只读观察器使用同一个实际 RTL 可执行模型，读写额外等待均为 3，正式成绩字段为 null。普通 O3 与原无观察器的 O3 运行逐项完全一致。实际记录位于交付包 `verification/competition_v2/cpu_pipeline/`。

| 指标 | 普通 O3 | O3 + unroll + no-if-conversion |
|---|---:|---:|
| CoreMark 精确计时周期 | 6,032,017 | 5,951,817 |
| 全程序有效周期 | 6,237,880 | 6,160,384 |
| 全程序退休指令 | 3,103,036 | 2,893,629 |
| 全程序 CPI | 2.01025 | 2.12895 |
| 条件分支 | 598,290 | 548,918 |
| 条件分支误预测 | 66,672 | 62,628 |
| 条件分支误预测率 | 11.1438% | 11.4094% |
| E 级有效阻塞周期 | 651,070 | 576,168 |
| I 读数据 beat | 6,360 | 20,960 |
| I 响应等待周期 | 2,385 | 7,860 |
| D 响应等待周期 | 547,198 | 547,375 |
| D 顺序 hazard 电平周期 | 221,478 | 257,566 |
| 最终 CRC | `fcaf` | `fcaf` |

计时周期减少 **1.3296%**，同样迭代数的吞吐增加 **1.3475%**。全程序退休指令、条件分支和误预测绝对数减少，但 CPI、误预测率、I 总线流量及部分 D 顺序等待上升。因此证据支持“这个代码生成组合在本模型下小幅更快”，不能据此称预测器更准确、访存全面改善或任何程序都变快。I 流量上升还说明需要在板上验证代码展开的缓存与带宽代价。

函数地址由各自 ELF 解析，不能复用旧地址：普通 O3 `core_bench_list` 是 `[0xb40003ac, 0xb400085c)`；调优版是 `[0xb40003b4, 0xb4000a2c)`。两个连续窗口各 1,024 周期，都有 128 周期前触发记录。

### 一段可核对的流水线事件

调优版窗口触发在第 **136,091** 周期，M 级条件分支 PC 为 `0xb4000438`；同周期 E 级 `0xb400043c` 被移除，I-AXI 发生一次 AR 握手。第 136,092 周期退休该分支。第 136,092–136,094 周期观察到未返回数据的 I 读事务，第 136,095–136,102 周期接收 8 个 I 读数据 beat。第 136,105 周期 F 观察点重新传递 PC `0xb4000428`，该指令在第 136,111 周期退休。

这个实例展示了条件分支纠正、年轻指令移除、前端空窗和取指事务重叠。**不能把这 20 周期全部当作分支本身固定惩罚**，也不能仅据此推断外部读请求一定是目标地址 cache miss；本有限轨迹没有记录该请求的地址。原始 CSV/VCD 可逐周期核查，PNG 只是其中 36 周期的展示。

## 4. 可选的被动 ILA pack 与真实网名

`t09_ila_probe_pack.sv` 是 256 bit 的纯组合打包模块，输出只能接调试 ILA，**当前没有实例化到生产设计**。没有反馈信号、寄存器或功能时序改动。`probe_pack_test.cpp` 经 Verilator 实际编译执行，检查 PC 字、五级 one-hot 标志位置、AXI/控制字段边界及保留位；也通过单独 `--lint-only -Wall`。这只验证打包与语法，不等于 PDS 实现或上板验收。

当前源码层级依据：`board/mes2l676-200hp/nx_ce64_board_logic.sv` 的实例 `soc`，下接 `rtl/soc/nx_soc_ce64.sv` 的实例 `cpu`。从该 board-logic 层起，原网名路径为 `soc.cpu.<net>`；最外层前缀必须在实际 PDS elaborated/netlist 中核对，不能照抄一个假定的顶层名字。综合可能重命名或优化网；以同一版网表实际可探测信号为准。

| pack 位 | pack 输入 | `T09Cpu` 原信号或表达式 |
|---|---|---|
| 31:0 | `fetch_response_pc` | `T09IBus_iBusRsp_stages_2_input_payload` |
| 63:32 | `decode_pc` | `decode_PC` |
| 95:64 | `execute_pc` | `execute_PC` |
| 127:96 | `memory_pc` | `memory_PC` |
| 159:128 | `writeback_pc` | `writeBack_PC` |
| 191:160 | `retire_instruction` | `trace_instruction` |
| 196:192 | `valid_mask` | bit 0=F input_valid；bit 1..4=D/E/M/W `*_arbitration_isValid` |
| 201:197 | `stuck_mask` | F valid 且非 input_ready；D/E/M/W valid 且 `*_arbitration_isStuck` |
| 206:202 | `fire_mask` | F output_valid 且 output_ready；D/E/M/W `*_arbitration_isFiring` |
| 210:207 | `remove_mask` | bit 0..3=D/E/M/W `*_arbitration_removeIt` |
| 211 | `fetch_flush` | `T09IBus_iBusRsp_flush` |
| 212 | `retire` | `trace_retire` |
| 213 | `execute_stall` | `trace_stall` |
| 214 | `conditional_branch` | `trace_branch` |
| 215 | `mispredict` | `trace_mispredict` |
| 218:216 | `pending_writes` | `dBusToAxi4Shared_pendingWrites_value` |
| 219 | `data_bus_hazard` | `dBusToAxi4Shared_hazard` |
| 220 | `data_refilling` | `dataCache_1_io_cpu_execute_refilling` |
| 221 | `execute_memory_enable` | `execute_MEMORY_ENABLE`，解释时还需 E valid |
| 222 | `execute_memory_write` | `execute_MEMORY_WR`，解释时还需 E valid 与 memory-enable |
| 229:223 | `axi_fire_mask` | bit 0..6=`iAxi_ar, iAxi_r, dAxi_ar, dAxi_r, dAxi_aw, dAxi_w, dAxi_b` 的 valid 且 ready |
| 236:230 | `axi_backpressure_mask` | 同一通道顺序，valid 且非 ready |
| 237 | `i_r_valid` | `iAxi_r_valid` |
| 238 | `d_r_valid` | `dAxi_r_valid` |
| 239 | `d_b_valid` | `dAxi_b_valid` |
| 240 | `reset` | `reset` |
| 241 | `i_r_last` | `iAxi_r_payload_last` |
| 242 | `d_r_last` | `dAxi_r_payload_last` |
| 243 | `rom_enable` | `rom_enable` |
| 255:244 | 保留 | 固定 0 |

硬件 pack 包含真实响应 valid/last，**不把仿真器 `ReadPort.active` 冒充可直接连接的硬件网**。若离线分析响应等待，必须在采样窗口内观测完整 AR→最后 R / 最后 W→B 事务，或额外加入经验证的被动事务计数器；窗口开头的未完成事务状态未知时，不能精确回填等待时间。

### PDS/板上闭环步骤（尚未执行）

1. 固定正式编译 ELF、binary、编译选项及其 SHA-256。从该 ELF 获取算法函数地址；本次调试地址仅适用于对应 debug binary。
2. 在单独调试候选工程中接上述实际网或实例化 pack，将 ILA 采样时钟接同一 CPU 时钟域，避免跨域直接采样。对新增 ILA 的网表重新运行 PDS 综合、布局布线、时序与资源检查，记录 bitstream、约束、工具版本和真实时钟。此目录没有宣称新增 ILA 已通过这些检查。
3. 先用 1,024 深度、128 前触发周期；256×1,024 只表示原始采样数据 262,144 bit（32 KiB），不是经过 PDS 的实际 BRAM/逻辑资源报告。
4. 对条件分支波形，触发 `probe[215]=1` 并匹配 M PC 的真实算法地址范围；若 ILA 不支持范围组合比较，就触发 mispredict 后依据 M PC 离线筛选。对访存波形可先触发原 data-refilling/hazard 信号，结合完整事务握手分析，不通过“停了几拍”猜测 cache miss。
5. 保存原始 ILA capture/CSV、同版 probe 配置、带绝对周期或采样序号的截图，以及相关 UART 原始日志。正式 CoreMark 要另外具备 performance/validation 两套 seeds、明确迭代数、至少 10 秒及实际时钟/存储位置证据。仅靠本目录的仿真波形不能关闭赛题的物理 ILA 要求。

### 打包模块的可重复编译测试

```sh
verilator --lint-only -Wall --top-module t09_ila_probe_pack \
  tests/cpu_pipeline/t09_ila_probe_pack.sv

verilator --cc --exe --build -j 2 -Wall \
  --top-module t09_ila_probe_pack --Mdir /path/to/new-probe-test \
  -CFLAGS '-O2 -std=c++17' \
  "$PWD/tests/cpu_pipeline/t09_ila_probe_pack.sv" \
  "$PWD/tests/cpu_pipeline/probe_pack_test.cpp"
/path/to/new-probe-test/Vt09_ila_probe_pack
```
