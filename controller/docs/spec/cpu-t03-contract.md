# T03 最小 CPU / 固件合同 v1

本配置是供 T09/T12 接续的仿真基线，暂用 PRELOAD 和 64 KiB 统一 RAM。它不冻结 T08 最终地址图，也不证明 Cache、动态预测、协议装载、DDR、PDS 或实板可用。

## 重建入口与身份

`make t03` 从锁定提交生成两个配置、编译固件、运行真实 CPU 并独立校验。`make t03-acceptance` 在新目录重建 seed 1 和 7，比较 ELF/RTL 身份，运行 CPU 保持复位的负例，并检查损坏证据会被拒绝。指定种子可用 `npu-python scripts/run_t03.py --seed 7`。

复用 T01 的 [工具锁](toolchain-lock.json) 和 [证据运行器](BUILD.md)。VexRiscv 提交固定为 `baf7dc82f855eddaf5b0a20a6802c526f127e38a`，SpinalHDL 1.13.0、Scala 2.12.18、项目 sbt 1.6.0、JDK 8、RV32 GCC 14.2.0、VCS X-2025.06。每次用 `git archive` 导出锁定提交到新的构建目录，不改用户级 checkout，不编译其中未跟踪的文件。输入源码和上游导出均存入证据；验收时逐字节比较两次独立构建的 ELF 和两种生成 RTL。

`evidence/T03/<run-id>/` 保存配置、源码及上游快照、工具实测、执行命令和退出码、ELF/BIN/HEX/map/反汇编、两种配置的 RTL、UART 引脚解码、退休轨迹、CSR 跳转、VCD 和独立检查 JSON。失败目录不覆盖。源码、固件、checker、配置、生成 RTL 和产物均有 SHA-256；无模型输入。所有源文件稳定性检查通过后才接受本次运行。

## CPU 配置

五级流水（Fetch/Decode/Execute/Memory/WriteBack），无 Cache、无预测、无 MMU、无 A/C 扩展。寄存器堆同步读，四处前递开启；使用 MulPlugin 和 DivPlugin。上游简单 I/D 总线接统一 RAM，读响应延迟一拍，写在握手时完成；UART 忙时对 UART 数据写反压。广泛随机反压、错误注入和外存行为由 T04/T09 验收。

必要机器态 CSR 包括 `mstatus/mie/mip/mtvec/mepc/mcause/mtval/mscratch`、只读 `misa/mcycle/minstret`。`misa=0x40001100`，异常、机器定时器中断和 `mret` 启用；未知 CSR 访问捕获。固件定向执行非法指令、定时器中断和两次返回。未执行所有 CSR、特权、访问错误或外部/软件中断测试，不宣称完整 ISA/特权规范认证。DBusSimple 没有 store response，本临时平台对越界写直接令仿真失败，不能把它称为已验收的 store access fault。

## 临时地址和启动

| 范围/地址 | 内容 |
|---|---|
| `0x80000000–0x8000ffff` | 64 KiB 统一 RAM；复位和 ELF 入口 `0x80000000` |
| `0x80008000` | `.data` 的运行地址；加载副本紧随 `.text/.rodata` |
| `.data` 之后 | `.bss`；启动代码逐字清零 |
| `0x8000f000–0x8000ffff` | 4 KiB 栈；初始 `sp=0x80010000`，16 字节对齐 |
| `0x10000000` | UART TX 数据，低 8 位，32 位写 |
| `0x10000004` | UART 状态，bit 0 表示忙 |
| `0x10000008/0x1000000c` | 64 位 `mtime` 低/高字，只读，每拍递增 |
| `0x10000010/0x10000014` | `mtimecmp` 低/高字，复位全 1 |
| `0x10000018` | 固定测试 seed，只读 |
| `0x1000001c` | CPU 自检签名，32 位写 |
| `0x10000020` | CPU 退出码，成功值 `0x600d0003` |

以上 MMIO 使用对齐的 32 位访问，不是 CLINT 或 16550 兼容接口。设置比较器先写高字全 1，再写低字，最后写有效高字。当前定向定时器测试不跨越 32 位低字回卷；通用运行时读 64 位计数应使用高/低/高一致性读取。

预加载前 RAM 填 `0xa5a5a5a5`，HEX 仅覆盖 ELF 的物理加载镜像；运行地址的 `.data` 与 `.bss` 保持非零毒值。CPU 启动代码初始化 gp/sp、禁用中断、设置 mtvec、搬运 `.data`、清 `.bss` 后调用 main。固件自行检查初始化结果和栈对齐。TB 无运行时 RAM 改写、寄存器注入或代写签名。异常入口保存所有调用者保存寄存器，C handler 返回恢复 PC，随后 `mret`。

## FENCE.I 与缓存维护

锁定上游的 IBusSimplePlugin 只为 FENCE.I 增加译码；本配置显式设置 `BranchPlugin(fenceiGenAsAJump=true)`。该插件等待较老指令离开后续流水段，将 FENCE.I 转成下一 PC 的跳转并冲刷预取/流水线。在此统一 RAM、写入握手即完成、无缓存的单核平台上，固件写完代码后执行 FENCE.I，再执行新代码。

固件测试改写紧邻 FENCE.I 的下一条 `addi a0,zero,1` 为返回 42 的指令；两者间没有额外跳转。checker 对照原 ELF 与退休流，要求改写位置实际退休 `0x02a00513`。这同时避免“执行了 FENCE.I 空指令但另一个跳转掩盖问题”的弱检查。

对锁定上游的静态核对还确认：IBusCachedPlugin 将 FENCE.I 接到 I-Cache flush；DBusCachedPlugin 的非标准管理编码 `0x0000500f`（rs1=0）接到全 D-Cache flush，rs1 非零选择对应行。普通 FENCE 是否等待写完成还受 `withWriteResponse` 等配置影响。这些是 T09/T13 的候选机制，尚无本卡行为验收；必须结合实际 cache 写策略和外部总线完成语义重验，不能将名称中的 flush 当成已验证的写回保证。

普通 FENCE 依靠本平台按序、握手完成的访存语义。未来 Cache/DMA/写缓冲配置必须定义并验收 D-Cache 写回/无效化、I-Cache 无效化、总线完成和所有权；不能沿用本卡的无缓存结论。T09/T13/T17 承接这些要求。FENCE.I 的规范依据见 [RISC-V Zifencei](https://docs.riscv.org/reference/isa/unpriv/zifencei.html)；本实现的具体选择以锁定上游 `IBusSimplePlugin.scala` 和 `BranchPlugin.scala` 为准。

## ABI 与独立 FPU 评估

正式基线始终显式 `-march=rv32im_zicsr_zifencei -mabi=ilp32`，不继承工具链默认的 A/C。ELF flags 必须为 0，属性只允许 I/M/Zicsr/Zifencei（允许 M 隐含的 Zmmul）。启动、链接、编译使用相同合同。`-lgcc` 选择工具链的 `rv32im/ilp32/libgcc.a`；测试使用运行时 volatile 输入，经 `__mulsf3` 和 `__addsf3` 算出 2.875，检查器要求 CPU 确实进入两个软件函数，结果位型为 `0x40380000`。

独立候选 `rv32imf` 使用同一五级基础、单精度 FpuPlugin、同步浮点寄存器堆，并显式启用独立的 `withDiv/withSqrt`。旧 `withDivSqrt` 路径在此版本含尚未实现提交跟踪的断言，必须保持关闭；该失败日志亦保留。锁定版本的 FpuPlugin 需要 `DBusEncodingService`，DBusSimplePlugin 不提供该服务；候选因此另用 4 KiB、单路、32B line 的 DBusCachedPlugin 和静态地址转换。它的数据总线接口不同，不能直接替换本卡 SoC 中的无缓存 CPU。初次直接组合失败的生成日志保留，作为该配置依赖的实测证据。这里只生成并通过 VCS 编译，绝不把它作为本卡执行配置。FPU 指令、FS 状态、FCSR、舍入/异常、非规格化数、硬浮点 ABI 与库均待 T09 专项执行验收；现阶段维持可用的软浮点基线。未进行综合、面积、频率或 PDS 映射比较。

## 观察与检查边界

仿真时钟为 100 MHz；UART 为 8N1，固定 16 拍/bit（加速仿真的 6.25 Mbaud，不是板端速率承诺）。SV 监视器只采样 TX 引脚；Python 再从 VCD 独立解码并逐字节比较。Python 用任意精度整数计算 32 组算术和内存散列，分别处理有符号截断除法及 RV32 回卷；固件另验证除零/溢出边界、byte/halfword lane 与符号扩展。观察到的签名同时与 UART、MMIO 和 VCD 比较。

`trace_retire/trace_pc/trace_instruction` 来自 WriteBack 的 isFiring、PC 和原始指令，FENCE.I 内部改写不污染原始指令记录。`exception_pending` 表示异常在流水段待处理；`csr_redirect` 包括进入 trap 与 MRET，**不是**专用异常脉冲。checker 将退休 CSV 与 VCD 时钟沿前的稳定信号逐条比较，要求已执行代码来自 ELF（唯一定向修改点除外）、M 扩展八种操作、软浮点函数、FENCE.I、两次 trap 和两次 MRET 均出现。上述观察端口不具有改变 CPU 状态的能力。

本卡固件自检不是完整 ISA 测试套件；定时器和异常仅覆盖列明用例。下载启动不得使用本卡预加载模式假装验收，T17/T18 必须另建禁用目标应用预加载的 PROTOCOL_BOOT 配置。
