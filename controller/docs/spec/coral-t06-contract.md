# T06 Coral 仿真合同 v1

producer: T06；consumers: T07/T08/T13/T14/T24。

`make t06` 锁定 `third_party/lock.json` 的 Coral commit、Bazel 9.1.0、上游交叉编译器归档及 RVV intrinsics；使用 T01 锁定的 VCS。缺少源码/Bazel 时按锁下载，已有源码必须干净且提交匹配，下载须校验 SHA-256。Bazel 依赖按上游 MODULE 锁复用 `build/T06-bazel/` 缓存；每次新建 VCS 编译目录、固件、自检镜像和证据目录。`make clean` 删除缓存，之后首次复跑需要网络重新获取工具和依赖。

正式入口为 `scripts/run_t06.py [--run-id NEW_ID]`。不能复用已有 run-id；成功与失败均保留原始命令、日志、退出码、配置/源码/checker/固件/工具身份、完整上游源码归档、生成 RTL ZIP、头文件、ELF、反汇编、AXI CSV、VCD 和输出。编译失败或缺少实际计算结果不会返回成功，也不会自动生成性能否决结论。

## 选定配置

| 项目 | 固定值 |
|---|---|
| 上游提交 | `382b5c12030ad8eb74ab8deafb2529301faeab16` |
| 选定 RTL target | `//hdl/chisel/src/coralnpu:rvv_core_mini_axi_cc_library_emit_verilog` |
| 标量对照 | `//hdl/chisel/src/coralnpu:core_mini_axi_cc_library_emit_verilog` |
| 模块 | `RvvCoreMiniAxi` / `CoreMiniAxi` |
| RVV | VLEN=128；RVV target 启用 RVV、Float、Zfbfmin、VectorBf16，标量 target 未启用 RVV |
| 本地存储 | ITCM `[0,0x2000)` 8KiB；DTCM `[0x10000,0x18000)` 32KiB |
| 控制窗口 | CSR 基址 `0x30000`，与当前默认 memory regions 一致 |
| AXI | 地址 32 位，数据 128 位，ID 6 位，主从各一组独立五通道 |
| VME 矩阵引擎 | 此 commit 存在 Zvt/PE 源码与独立 VME target；所选 RVV target 的 `enableVme=false`，不参与本卡执行 |

所列扩展来自生成配置；执行验收覆盖下面的具体指令，不能推广为全部 ISA/浮点/BF16 合规。改变 commit、target、TCM、接口宽度或编译器后重跑 T06；更换格式/算子还需 T05/T07 验证。

## 装载、启动和结果

`AXI_SUBORDINATE_LOAD` 是测试台 BFM 装载模式，不是 UART/SD 启动。采用 T04 的 checked ELF 解析器，再限制 PT_LOAD 完全位于 ITCM 或 DTCM、无压缩指令标志、入口 4 字节对齐。显式通过 AXI 写入整个 40KiB TCM，包括清零区域和测试输入；随后完整回读比较。没有调用 SRAM backdoor 装载接口。

CSR `+0x00` bit0=reset、bit1=clock gate，复位值 3；`+0x04` 为入口 PC，`+0x08` bit0=halted、bit1=fault。128 位窄访问必须按地址选择数据 lane 和 WSTRB：入口字在 `[63:32]`、strobe `0x00f0`。写入口并读回后向控制寄存器写 0 启动。等待真实 halted，检查 fault=0 和 CSR 状态，再经从接口读出整个 DTCM。

上游浮点示例注入 8 对非零/正负输入；上游 RVV 示例计算 1024 个 INT8 加宽和。自定义 67 元素程序以明确 RVV intrinsics 执行 INT8 加载、INT16 加宽加法/乘法、INT32 规约、存储，涵盖 ±128/127 边界和非整向量尾部；独立 Python 整数运算生成期望值并检查保护区。上游示例 `_ret` 和自定义 `done` 都必须正确，不能仅凭 halted 判 PASS。

AXI BFM 使用单拍事务、独立 AW/W 发送延迟及 B/R 接收反压，seed 1/7 控制确定性时序。检查完整装载/回读、每笔响应/ID、握手数量、阻塞稳定性与结果 dump；同 seed 的完整 CSV 必须一致，不同 seed 时数据必须一致。保持 reset 负例、损坏输出/trace/反汇编负例必须失败并保留 FAIL 证据。周期数包含释放控制写与观察完成的 BFM 开销，只是这一仿真测量窗口。

## 平台模型与下游边界

使用上游生成 ZIP 自带的 `Sram.v`、`ClockGate.sv`、`RstSync.sv`。未定义 ASIC 工艺或 FPGA 宏；使用 `USE_GENERIC`，VCS 模式链接上游 `sram_backdoor.cc` 的存储函数以维持同步读写、128 位数据和逐字节写掩码。该 C++ 代码只实现 SRAM 存储，不实现 CPU/RVV 运算。SRAM 初始随机数据被 AXI 全量覆盖，未调用其 ELF/patch 预加载函数。ClockGate 使用低电平锁存使能，保留门控时序；没有强制时钟常开，也没有实现 FPGA 原语。

外部 AXI 主端在本卡是禁止访问的监测边界：任何请求立即失败。它没有接入 T04 外存模型，也没有外存吞吐证据。T04 当前只验收 32/64 位；T07 必须明确验证 128 位及 6 位 ID 的桥接/扩展、属性语义和超过 TCM 的工作集，再测 Qwen 真尺寸算子。不能把这一小例子的 TCM 周期当作 DDR、整网速度或矩阵引擎性能。

本卡不验收 VME 运算、完整 BF16/浮点指令集、Cache/外存路径、SoC 主控联调、PDS、面积、Fmax 或实板。
