# T14 Coral 外存分块合同

Producer=T14；consumers=T15/T16/T27。沿用 backend-api-v1、model-pack-v1、
w8a8-g64-fp32-v1 和 memory-map-v1。这里定义 Coral 固件私有 ABI 与传输组件，
完整数值能力仍须 T15 验收，真实主控闭环仍须 T16 验收。

`firmware/drivers/accel/stream.c` 是真实 Coral RVV 微程序；`stream.h` 与 `stream.ld`
明确固定布局。原生从口装入 ITCM/DTCM 并回读，写 entry 后启动，最终使用 mpause。
权重由 Coral 128-bit/ID6 AXI 主口直接读，经过 T13 guard 到 T04 行为外存。
组件测试以 cocotb 驱动原生从口，没有 VexRiscv 主控或第二种计算后端。

参数位于本地 0x10000，96 bytes，24 个小端 u32。结果位于 0x10100，104 bytes；
6 个 ABI/身份 u32、status、valid、tiles、rows、checksum、reserved，随后是 7 个 u64：
逻辑输入 bytes、逻辑输出 bytes、核心 cycles、load/compute/write/other cycles。
ABI=0x53543134；size、非零 session/sequence 与 reserved 全零必须先验证。
身份由提交者提供并逐次递增；公共 API 会话生命周期和全局 owner 仍由 T13 驱动管理。

COPY 接受 rows、row_bytes、source_stride、destination_stride；所有起始地址/行 stride
16B 对齐，row_bytes 可含非整拍尾部。先以受检查运算验证整段 span、权限和输入输出
不重叠，再每 128 行调度一块。每次复制最多 64B，同时截断于源和目标的 4KiB 边界。
真实 RVV 向量长度约束最后字节，最终 WSTRB 不改写保护区；源端 AXI lane overfetch
按实际接口记录。64B DTCM scratch 有界复用，不把整个权重块暂存片上。
COPY 的 checksum 是所有逻辑输入字节的无符号加和，仅为传输诊断；不代表 W8 算术。

LINEAR 是传输路径上的 W8 计算探针，接受 M=1/4、K=896/4864、N<=151936，
自行以 N<=128 分块；Y 的 output_stride 是全局 token 行跨度，必须按 FP32 的 4B 对齐，不能使用 tile 宽度替代；不要求各 token 行 16B 对齐。
Coral 从外存加载 Aq/Sa 到静态暂存，直接流式读 Wq/Sw/bias，每组 RVV INT32 dot，
Coral 标量 FP32 恢复。数据采用 T10 合法 fixture 与冻结 T05 参考，生产能力 mask
保持零，直到 T15 覆盖全部算子/形状和完整词表投影。K65 包可 COPY 验物理补零，
LINEAR 明确返回 EUNSUPPORTED。

片上布局：8KiB ITCM；0x10000 参数；0x10100 结果；0x10200 起静态 Aq=19456B、
Sa=1216B、scratch=64B；0x16ff0–0x16fff 为 16B 栈保护区；0x17000–0x17fff 为 4KiB 栈。
链接 ASSERT、ELF/map 和原生回读栈 sentinel 共同验证实际占用。静态暂存与栈不重叠，
权重和输出均保留在 DDR。串行调度为本版已选基线；尚未启用双缓冲/重叠。

微程序计数区间不重叠，load+compute+write+other=cycles，mcycle 用 high/low/high
读取。payload_read/write 是逻辑工作量。`nx_stream_counters.sv` 在 guard 上游实际握手
记录 R 有效 transfer bytes 和 WSTRB popcount、五通道计数、在途等待周期；只在 drained
边界清零。独立 AXI trace 逐笔重建地址、拍数、ID、last、字节数据和计数；物理读冗余
与逻辑 bytes 分开报告，不能把 scalar lane overfetch 隐藏为有效模型 bytes。

正常成功要求：halt、无 fault/sticky bus error、完整身份、valid=1、全部 R/B drained。
错误响应使输出无效，即使部分 W 已写入；恢复先 isolate，等已经握手的所有事务排空，
再执行 native control=3，不复位 guard 或外存，不丢弃响应。长停顿用 T04 环境延迟制造，
在途未完成时不能返回成功。未知地址、高地址回卷/跨分区、权限、对齐、不支持形状均
在请求验证阶段拒绝；21 个坏 T10 包由既有独立包读取器在提交前拒绝，明确为桌面前置
校验，不冒充坏包被真实 RTL 解析。

`make t14` 是完整 VCS+cocotb 注册矩阵；`make t14-smoke` 仅开发快速检查；
`make t14-test` 验独立 scoreboard 对丢/重复事务、错误数据/计数及提前响应的拒绝。
`npu-python scripts/run_t14.py --verify-archive evidence/T14/<run-id>` 重验归档内容、
矩阵、XML、独立检查、AXI trace 与代表性 VCD 窗口；仅完整矩阵可关闭 T14。
