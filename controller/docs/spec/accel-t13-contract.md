# T13 共享所有权与 Coral 原生传输

Producer T13；consumers T14/T15/T16。沿用 system-v1/backend-api-v1/memory-map-v1，
不更改数值或物理分区，不添加通用描述符。T13 私有 probe ABI 不属于 W8 数值能力。

## 实现与范围

`firmware/drivers/accel/accel.{h,c}` 实现同步单在途、全局 owner、64 位 session/sequence、
上传/回读、原生启动、轮询、结果身份、超时隔离和显式恢复。`target.c` 使用 RV32 MMIO、
FENCE IORW 和 mcycle 高/低/高一致读取。中断只通知并 W1C 确认，不决定成功。
本平台单 hart，无线程提交；中断服务只能确认通知，不调用提交/初始化。
接受后的重入返回 EBUSY，FAULTED 拒绝新任务；失败输出始终无效。

`rtl/soc/nx_accel_bridge.sv` 接 T09 CPU D AXI，区分原样 DDR 地址、桥寄存器和 Coral
本地地址。CPU 每次写必须完成 B，后续读/MMIO 才能发出。CPU 的 write-through Cache
部分写允许合法的未对齐 AWSIZE=2 与 WSTRB；读支持 Cache 的 INCR refill，写只接受
本 CPU 发出的单拍事务。32→128 按地址低四位保留数据 lane、WSTRB、响应；不吞写错误，
将其保存于 sticky 状态以补足 T09 CPU 不传播 store B 错误的边界。

`nx_accel_guard.sv` 接 Coral 128-bit/ID6 外存主口，提供单读、单写在途，保留 ID、
合法 INCR burst 和反压。拒绝的读返回完整 DECERR 拍数，拒绝的写消耗全部 W 后返回 B。
允许地址严格依照 T08 四个共享区，模型只读，CPU private/tokenizer/MMIO/保留区不可访问；
检查整次 burst 的分区、32 位回卷、4KiB 边界、size/alignment。上游必须遵守 AXI
WLAST/WSTRB/稳定性合同；本模块不是任意失效主设备的容错协议修复器。

测试组合为真实 T09 两路 16KiB I/D Cache 主控、真实固件、上述 RTL、T04 外存，和
**CORAL_NATIVE_TRANSACTION_TEST_DOUBLE**。替身模拟原生 TCM/CSR 及 AXI probe 事务，
不执行微程序；CPU 实际编译、上传、回读 native Coral probe ELF 的字节。
`probe.c` 的 XOR 数据变换仅用于独立检验可见性，不能作为数值内核或 W8 能力。
`nx_query_caps` 上报 operation/vector mask=0；公开 numerical run 入口返回 EUNSUPPORTED。
T14/T15 安装真正内核及 shape/layout 适配，T16 必须用真实 Coral RVV 重新验收完整路径。
T13 未启动第二条计算后端路线。

## 所有权和错误恢复

CPU private/tokenizer 使用 T09 Cache 属性，其余地址非缓存，无物理别名翻译。
模型和 tokenizer 在此推理模式已封存；装载写入口仍由 T17/T18 负责。
CPU 指令口沿用 T09，未新增 PMP/特权隔离声明；本模块保护数据/后端通道。

共享 KV/workspace/shared_io 采用全区互斥所有权，保守地阻止 CPU 在后端 owner=1 时
读写共享可写分区。CPU 发布数据先 FENCE，再读取桥状态；桥的严格 B 排空顺序是
跨主设备完成保证。FENCE 本身不是 Cache clean，共享 buffer 不依赖 Cache flush。
主控只上传微程序/参数，不搬运模型权重；probe 由后端 AXI 自行读写共享数据。

正常流程：验证→取得 owner→清除记录/通知→写私有参数→入口回读→control=0→轮询。
成功必须同时满足原生 halt、无 fault/总线错误、完整匹配的结果记录和后端所有响应
完成。错误返回 FAULTED，保存本次结果与错误地址、保留 owner、隔离新请求。
`nx_wait` 返回最近已接收请求的保存结果；拒绝不消耗 sequence。

恢复先 isolate，再等 guard idle，之后才能 control=3、清 sticky、重新上传并回读、
清结果记录、释放 owner、递增 session 和清空逻辑 KV。排空/上传超过恢复时限时仍为
FAULTED，不更改 session、不释放缓冲、不清空 AXI 状态。已经握手的 AW 或先到的 W
都必须处理完；全局复位只用于系统启动，不能作为超时恢复手段。桥与 guard 接线必须使用 `guard.isolate = bridge.isolate || !bridge.owner`，
空闲且 CPU 持有 buffer 时也禁止后端发起新事务；测试组合按此接线。
当前没有“丢失响应后强制成功恢复”能力；响应永不返回则持续隔离并返回超时。

## 寄存器及固件私有记录

全部小端，32 位访问。桥寄存器位于 T08 的 UART/timer/诊断 4KiB 区中，不改变分区。

| SoC 地址 | 含义 |
|---|---|
| 0x10000100 | bit0 owner，bit1 isolate；仍有在途时拒绝释放 owner 或解除 isolate |
| 0x10000104 | bit0 guard drained，bit1 CPU sticky IO error，bit2 backend sticky IO error |
| 0x10000108 | 写入后仅在 drained 时清错误 |
| 0x1000010c | bit0 中断 pending，W1C；只记录通知 |
| 0x10000110 | 最近出错的 AXI 地址；backend sticky 有效时优先 |
| 0x10000114 | bit0 中断使能 |
| 0x20030000/4/8 | Coral 原生 control/entry/status，字段沿用 T08 |

私有参数在 Coral 本地 0x10000，共 48 bytes，12 个 u32：
ABI=1、size=48、session lo/hi、sequence lo/hi、opcode、input SoC、output SoC、words、xor_mask、reserved=0。
结果在本地 0x10100，共 32 bytes，8 个 u32：ABI=1、size=32、session lo/hi、sequence lo/hi、status、valid。
当前 opcode=0x54503133 仅表示传输 probe，words=1…16，buffer 16B 对齐、不重叠、整段位于一个合法分区。
不序列化 `nx_context`、`nx_call` 或 C enum/struct。程序限制 8KiB ITCM、4B 对齐入口，
在上传前检查 CRC32 并逐字回读。CRC/回读用于传输完整性，非签名认证。
参数和结果预留与 DTCM 顶端栈分离；生产 footprint 由 T14 再核对。

错误码沿用 T08：地址/溢出 EBOUNDS、对齐 EALIGN、未支持 shape/opcode EUNSUPPORTED、
版本 EVERSION、重复/过期身份 ESTATE、重入 EBUSY、时限 ETIMEOUT、核心/记录 EFAULT、
总线/上传 EIO。成功才设置 stats.output_valid；参考 ticks 按 validate/upload/execute 分段，
其和等于 elapsed。未测的 backend_cycles/AXI bytes 不设置 valid 位。

## 验证入口

`make t13` 是完整注册矩阵；`make t13-smoke` 单 seed；`make t13-test` 是主机边界测试。
`npu-python scripts/run_cocotb.py --task T13 --suite full` 与完整 regression 相同。
归档：`npu-python scripts/run_t13.py --verify-archive evidence/T13/<run-id>`。

真实固件覆盖连续重用、6 个成功数据集、halt 早于 B、迟/丢中断、核心 fault、超时、
读/写 SLVERR、私有区 DECERR、旧 sequence、短恢复时限失败后排空、坏上传以及封存权限。
单独的 cocotb guard 组件激励覆盖 AW/W 乱序、先到 AW/W 后 isolate、burst 拍数/ID、
读反压、分区/4KiB/地址回卷和只读权限，明确不冒充 CPU 发出的这些组件流量。
独立 scoreboard 比较 CPU 真正读取并报告的数据、native lane/WSTRB、AXI 请求/响应及 owner；
VCD 与被动记录逐笔交叉核对。PRELOAD 只装 ROM/CPU 私有程序，不预填最终输出。
