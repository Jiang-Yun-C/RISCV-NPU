# 请求区间 PMU（NPR1）

这是独立于 CPU ISA/CSR 的被动 SoC 观察模块，`nx_ce64_request_pmu.sv`。
它不驱动被观察的 AXI、退休或控制信号，不替代已有 CE64 perf_snapshot。
`ENABLE_REQUEST_PMU=0` 删除该模块；板级把相同参数传给本地设备，禁用时 capability=0。

## 接口与冻结边界

| 地址 | 含义 |
|---|---|
| `0x100000b0` | 下一个 START 的 32-bit tag；运行中写入不改变当前 tag |
| `0x100000b4` | 命令：START=1，CAPTURE=2，STOP=3，CLEAR=4 |
| `0x100000b8` | 能力常量 `0x3152504e`（NPR1）；禁用时 0 |
| `0x100000bc` | 当前状态/ABI，等同冻结块 word1 |
| `0x10000300` | 冻结块，64 words，位于原 telemetry 的保留上半部分 |

控制仅在实际 local MMIO 的成功 B 握手后应用，并要求单拍、32-bit、完整字节使能、WLAST。
AW/W 可分开到达；回包反压不会重复触发。失败 B 不触发命令。
START 提交边沿不计入区间；其下一个时钟边沿开始计数。
CAPTURE/STOP 将提交边沿的事件计入并在同一时钟锁存所有计数，STOP 同时停止。
因此区间涵盖端点控制和流式传输中实际执行的工作，不等同无干扰的纯算子计时。

运行中再次 START/CLEAR、停止时 CAPTURE/STOP、错误命令格式会置 sticky protocol error。
CLEAR 仅在停止时清空状态、tag、快照序号和计数。START 清新窗口的 live 计数和 overflow，
保留快照序号。每次 CAPTURE/STOP 加一；序号已达 `0xffffffff` 时拒绝捕获并置错，不回绕。
此时 STOP 仍停止区间，但保留先前冻结数据，允许后续 CLEAR 恢复；固件必须把这次捕获报告为失败。
固件可在停止后 CLEAR；不要在一份完整请求证据中无记录地重置序号。

状态 word1：高 16 位为 ABI=1；低位 0=active、1=valid、2=protocol error、
3=live overflow、4=frozen overflow。word2 为冻结 tag，word3 为快照序号。
其后 24 个 64-bit 小端计数占用 word4–51，word52–63 保留且为零。
冻结 tag/序号/计数只在 CAPTURE/STOP 或 CLEAR 改变；状态中的 active/live overflow 可变化。
C API 对读前/读后序号、tag、valid/error/overflow 进行核对。

## 事件定义

| 索引 | 定义 |
|---:|---|
| 0 | 区间核心时钟周期 |
| 1 | T09 trace_retire |
| 2 | Execute valid && stuck |
| 3 | Memory firing 且 opcode=0x63 的条件分支 |
| 4 | 上述条件分支纠错；不包含 JAL/JALR |
| 5 / 6 / 7 | CPU I AR 事务 / R 拍 / R 有效载荷字节（每拍 4 B） |
| 8 | I ARVALID && !ARREADY 周期 |
| 9 / 10 / 11 | CPU D AR 事务 / R 拍 / 按该读事务 ARSIZE 计算的有效载荷字节 |
| 12 / 13 / 14 | CPU D AW 事务 / W 拍 / 实际 WSTRB 的有效写字节 |
| 15 | D AR 或 AW 地址阻塞周期（同拍只算一次） |
| 16 / 17 / 18 | CE AR 事务 / R 拍 / ARSIZE 有效载荷字节 |
| 19 / 20 / 21 | CE AW 事务 / W 拍 / 实际 WSTRB 有效写字节 |
| 22 | CE AR 或 AW 地址阻塞周期 |
| 23 | I/D/CE 的 R，以及 D/CE 的 B，发生错误响应握手的数量之和 |

事件会重叠，不能相加成100%的互斥耗时。第23项不是独立故障数量。
CPU D 观测包含 MMIO、SRAM、DDR；CE 是 guard 上游的实际128-bit接口。
字节数是这些接口的逻辑有效载荷，不能称为 PHY 突发流量或控制器带宽。
每个读端口按当前架构的一笔未完成读保存 ARSIZE；不支持未来多ID乱序读时原样复用。
I AR 可观察实际取指事务，D AR 包含 uncached 访问；这里没有新增 HPM CSR 或笼统的 cache-miss 指标。

所有计数饱和为全一并置溢出标志；输出始终扩展到64位。
`COUNTER_WIDTH=8` 仅用于边界验证，生产实例使用默认64位。

## 软件与验证

`firmware/runtime/board/request_pmu.h` 通过 read32/write32/fence 回调访问。
`available` 同时验证能力、快照 magic、ABI；旧位流或未连接快照不能误报可用。
32-bit硬件tag应与软件64-bit session共同记录；软件须定义低32位重用策略。

```sh
python3 tests/request_pmu/run.py --verilator /path/to/verilator --output /new/pmu-results
```

测试执行64位及8位饱和实例，以独立握手计数 oracle 比较每份24项快照，并检查失败B、
字节使能错误、重复START、idle STOP、冻结稳定和reset。C API另验证旧位流、不同ABI、
错tag、读过程中序号变化及64位字拼接。这些是数字RTL/API证据；新增时序/资源和板端采集需独立取得。
序号上限用测试专属的状态置入抵达边界，检查不回绕、冻结数据保持、STOP 后可 CLEAR 恢复。
