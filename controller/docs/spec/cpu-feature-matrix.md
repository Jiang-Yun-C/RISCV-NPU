# T09 CPU 功能与实现边界

配置身份以 `cpu_gen/src/main/scala/nexusrv/GenT09.scala`、锁定上游及
`cpu_gen/patches/*.patch` 的源文件 hash 为准。实际验收结果见 [T09 报告](../reports/T09.md)。
本矩阵记录实现和定向覆盖，不声称完整特权规范或赛事资格已通过。

## 候选配置

| 项目 | soft（默认交接） | hard（独立候选） | nopredict（对照） |
|---|---|---|---|
| ISA / ABI | RV32IM+Zicsr+Zifencei / ILP32 | RV32IMF+Zicsr+Zifencei / ILP32F | 与 soft 相同 |
| 流水线 | Fetch/Decode/Execute/Memory/WriteBack 五级 | 相同 | 相同 |
| I / D Cache | 各 16KiB、2 路、32B line、256 sets | 相同 | 相同 |
| 预测 | DYNAMIC：256×2-bit 饱和方向表 | 相同 | NONE |
| 寄存器堆 | 32×32、同步读、zeroBoot 初始化 | 另含同步浮点寄存器堆 | 与 soft 相同 |
| 访存 | 32-bit AXI、I 只读 / D 五通道、无 ID，INCR refill | 相同 | 相同 |
| D 写策略 | write-through；缓存管理指令做无效化，无脏行写回 | 相同 | 相同 |
| 特权 | M 态；无 U/S、MMU/PMP、A/C、调试模块 | 相同 | 相同 |
| FPU | 软件 libgcc | 单精度 FpuPlugin，独立 withDiv/withSqrt；withDivSqrt=false | 软件 libgcc |

无 Cache/无预测对照继续使用可重建的 `GenT03.scala` 与 `make t03`；其临时地址图和
UART 引脚测试保持历史合同，不能直接拿跨平台总周期计算 T09 加速比。T09 的 nopredict
与 soft 使用同地址、固件和 Cache，适合隔离预测行为；这里不提交 CoreMark 成绩。

## 地址与缓存维护

reset PC=0x00010000，Boot ROM 经同步紧耦合口旁路 I-Cache；应用、数据和栈均在
T08 的 `cpu_private`：入口 0xb4000000，SP=0xb8000000。测试函数位于
0xb4010000/0xb4012000/0xb4014000，输入数据位于
0xb4100000/0xb4102000/0xb4104000，相隔 8KiB、同组不同 tag。
D-Cache 仅将 [0xb4000000,0xba000000) 视为 cacheable；MMIO/共享区走 uncached。
本卡并未实现完整 SoC 地址权限防火墙或 Coral 共享互连；T13/T14 仍需接入。

- `0x0000500f`、rs1=x0：全 D-Cache 无效化。外部环境修改 backing store 后，CPU 必须重新 refill 并读到新值。本卡没有把 invalidate 误称为 write-back。
- FENCE.I：I-Cache flush 与 `fenceiGenAsAJump=true` 同时启用，丢弃预取旧指令；固件相邻 store/FENCE.I/被改写指令验证 1→42。
- D AXI 适配器以 B 握手释放 pending-write 计数，后续 D 读等待 pending writes 清空。但普通 FENCE 本身不提供已验收的跨主设备完成保证；T13 必须定义并复验共享所有权与写完成屏障，不能仅引用本卡短延迟 FENCE.I 用例。
- 所有运行均为 PRELOAD；Boot ROM 和应用输入可预载，结果区不预填。UART/SD 协议启动由 T17/T18 接续。

## 异常、中断与 CSR

“已测”指真实固件执行、独立 AXI/MMIO/退休观察及 mcause/mepc/mtval 对照。

| cause | 实现与覆盖 | 明确边界 |
|---|---|---|
| 0 指令地址未对齐 | JALR 到 0xb4010002，记录 faulting PC 与目标地址 | IALIGN=32，不支持 C |
| 1 指令访问错误 | 0xbc000000 DECERR；错误后正常取指、中断处理继续执行 | ROM 紧耦合口无 error 输入；没有 PMP |
| 2 非法指令 | 0xffffffff、未实现 CSR 0x7ff、写只读 mcycle | 非完整 ISA/CSR 组合穷举 |
| 3 breakpoint | EBREAK 与 MRET 返回已测 | 锁定核 mtval=0x00100073（指令编码），不是地址；保留符合性缺口 |
| 4 load 未对齐 | LW 到 0xb4100001 | 不模拟非对齐拆分 |
| 5 load 访问错误 | uncached DECERR、cacheable SLVERR refill | 不包含页表/PMP |
| 6 store 未对齐 | SW 到 0xb4100001 | 异常签名已测；不是全部 store 原子性验证 |
| 7 store 访问错误 | **未实现端到端传播** | 上游 D AXI adapter 消费 BRESP，却不把错误传回 CPU；不能计为通过 |
| 8 / 9 U/S ECALL | 未实现 | 无 U/S 模式 |
| 10 / 14 | 保留编号，不生成 | 不冒充功能覆盖 |
| 11 M ECALL | ECALL 与 MRET 返回已测 | 锁定核 mtval=0x00000073；保留符合性缺口 |
| 12 / 13 / 15 页错误 | 未实现 | 无 MMU/页表/S 态 |
| 其他扩展异常 / NMI / 双重陷阱 | 未实现或未纳入候选 | 规范版本及赛事“完整”边界仍由 U01 关闭 |
| IRQ 3 / 7 / 11 | software/timer/external 三类异步输入，CSR 签名、ack、MRET 已测 | 外部 cocotb 按周期调度引脚；不是板级中断控制器验收 |

中断入口核对 MPP=3、MPIE=1、MIE=0；观察到每次异常/中断对应一次 MRET。
中断 mepc 随合法时序变化，以实际程序范围、对齐、返回与后续完成检查；同 seed 的
完整退休/事务序列另做逐摘要复现。中断 mtval 保留前一异常的值，不当作新地址。

| CSR / 指令 | 配置 | 验证边界 |
|---|---|---|
| misa | 固定 I/M，hard 再含 F；写入忽略 | 读取值核对；不是可动态切换 ISA |
| mstatus / mie / mip | 机器态 MIE/MPIE/MPP，MSIP/MTIP/MEIP；hard 含 FS | 三类中断/返回；FS 启动、dirty 状态 |
| mtvec | READ_WRITE，direct，xtvecModeGen=false | trap_entry；未配置 vectored 模式 |
| mepc / mcause / mtval | READ_WRITE | 捕获、mepc 改写与返回；mcause/mtval 的软件写边界未穷举 |
| mscratch | READ_WRITE | 往返值 0x76543210 |
| mcycle[h] / minstret[h] | READ_ONLY | 低字与外部时钟/退休计数对照；写 mcycle 触发非法；高字溢出未测，不能声称可写机器计数器符合性 |
| mvendorid / marchid / mimpid / mhartid | 未生成 | 不是完整 machine information CSR 集 |
| ucycle / uinstret / time | 未生成 | 运行时不可假定这些别名可读 |
| mcounteren / mcountinhibit / HPM | 未生成 | 后续计数扩展需重新验收 |
| PMP、medeleg/mideleg、satp、S/U CSR | 未生成 | 无隔离/分页/委派能力 |
| WFI | wfiGenAsWait=true | 本次程序用 NOP 等待；WFI 唤醒语义尚未定向验收 |
| fflags / frm / fcsr | 仅 hard | DZ、NV、NX、sticky flags、动态 RTZ；soft 保留库路径 |

## FPU 数值与库边界

硬浮点启动先设置 mstatus.FS 并清零 FCSR/32 个浮点寄存器，再进入 C。
两种 ABI 分别编译链接，未混用 ILP32 与 ILP32F。测试包含乘加的确定位模式、独立编译
单元的浮点参数/返回、libm sqrtf、除零 +∞/DZ、负数平方根 canonical NaN/NV、2.75→2 的
动态 RTZ/NX。只改 frm 不清除已有 NV，最终 fcsr=0x31；最后清零并读取 FS。
整数和这些确定的浮点位模式均精确比较，不使用放宽容差。

尚未做完整 IEEE-754、全部舍入模式、非规格化输入/输出、overflow/underflow、融合乘加
极端值和跨中断浮点上下文压力测试。hard 是已执行这些用例的独立候选，默认下游仍采用
soft；若发布选择 hard，应补充所需数值/上下文回归并加入 T28 发布依赖。

## RAM、读写端口与后置实现检查

| 存储 | 逻辑规模 / 端口 | PDS 必须核对 |
|---|---|---|
| 每路 I 数据 | 2048×32；同步读 + refill 写 | 双端口映射、读延迟、同地址读写语义 |
| 每路 I tag | 256×(19-bit tag+valid+error)；同步读 + 写/清零 | reset flush 清掉 valid；不能依赖 X 值 |
| 每路 D 数据 | 2048×32；同步读 + 4-byte mask 写 | byte enable、refill/store 合并、read-during-write |
| 每路 D tag | 256×(19-bit tag+valid+error)；同步读 + 写/无效化 | valid/error 和 refill 原子更新 |
| 整数寄存器堆 | 32×32；两个同步读口、一个写口 | zeroBoot 的初始化文件、x0、RAW 由已启用旁路处理 |
| 预测历史 | 256×2；同步读、单写口 | reset 后复用写口逐项清零 256 拍，期间停止取指；随后训练 |
| 浮点寄存器/scoreboard | 单精度 FPU、同步寄存器读，内部多路访问/仲裁 | 根据生成 RTL 核对实际复制/端口、异步 scoreboard 的 write-first 警告；未做器件映射保证 |

实际生成文件包含寄存器初值 `.bin`，runner 按 case 复制并校验身份。缺文件警告会使
验收失败。Cache tag 由硬件 reset flush 清理。没有以 RTL 仿真推断 BRAM 数量、频率、
资源利用、CDC/RDC 或板级可用性；这些由 T22 以后处理。

## 本地修正与观察口

锁定上游保持不变，构建时在导出的隔离副本应用三个可审阅 patch：

1. `predictor-reset.patch`：预测表使用同一写口逐项复位，禁止未初始化历史进入执行。
2. `cache-refill-error.patch`：错误 refill 的最后一拍仍标记当前行，但清除累积错误供下一行使用。
3. `cache-replacement.patch`：两种 Cache 在完成 refill 后轮换 victim；不再由空闲/反压拍数决定下一次 victim。是全局轮换，不声称 LRU 或每组最优替换。

只读观察口记录 writeback firing（退休）、PC/原始指令、execute valid&&stuck（停顿周期）、
memory firing 条件分支和纠错。nopredict 的同一纠错位表示 taken redirect。
周期来自 10ns 时钟；VCS/cocotb 墙钟仅用于超时，不代表硬件性能。分支测试两次 64 轮循环，
独立检查 128 次条件分支与结果 384，并比较预测/无预测纠错行为。
