# UART 启动与镜像合同 v1（T17）

复用 T09 Cache 开启的 RV32IM、T08 地址图及 T04 分页行为内存。Boot ROM 位于
`[0x10000,0x20000)`；下载器的 BSS/栈位于 Boot SRAM `[0x20000,0x30000)`。
应用只能写入 `[0xb4000000,0xb7ff0000)`，排除 CPU 栈保留区；单幅镜像为
1–65536 bytes，基址与入口须 4B 对齐，入口前后至少包含完整指令。
所有检查使用减法防止 32 位地址回绕。T18 接收相同的地址、入口与 CRC 规则。

串口为 8N1、LSB first。仿真时钟周期 10ns、每位 64 周期；这是加速仿真配置，
板端 baud divisor 仍须按实际时钟配置。UART 是真实 RTL 的 TX 和双同步 RX/64B FIFO，
MMIO 经真实 AXI 路由器进入外设；Python 只驱动 RX 引脚与观察 TX/总线。

| 偏移 | 寄存器 |
|---|---|
| 0x00 | TX data，busy 时写通道反压 |
| 0x04 | status：bit0 TX busy、bit1 RX available、bit2 framing error、bit3 overflow |
| 0x08 | RX FIFO data，成功读地址握手出队一次 |
| 0x10/0x14 | 显式启动模式与 PRELOAD 长度（仿真配置输入） |
| 0x20 | fatal trap code，测试要求为 0 |
| 0x24/0x28 | 应用执行/数据签名，独立观察点 |
| 0x30 | 固件记录加载来源：0 PROTOCOL_BOOT、1 PRELOAD |

每包为 `NXU1`（4 bytes）＋六个 little-endian uint32：command、sequence、
destination、length、entry、image_crc32；随后为可选 payload 和包 CRC32。
CRC 为 IEEE CRC32/ISO-HDLC（poly 0xedb88320，init/xorout 0xffffffff），
覆盖 magic、全部头字段和 payload；C 使用位递推，独立主机参考使用 zlib。

| command | 含义 |
|---|---|
| BEGIN=1 | seq=0，destination/length/entry 定义完整连续镜像，image_crc32 定义最终镜像；无 payload。成功清除旧 session，next=1 |
| DATA=2 | 1–256B payload，seq=next，destination=base+received；entry/image_crc32 均为 0。整包 CRC 校验通过后才写 RAM |
| RUN=3 | seq=next，重复原 BEGIN 的镜像描述；无 payload。必须收齐所有字节、整幅内存 CRC 正确，才允许执行 |

应答为 `NXAK`＋sequence/status/next_sequence 三个 uint32＋CRC32，固定 20 bytes。
status：0 OK、1 DUP、2 packet CRC、3 range/entry、4 sequence、5 timeout、
6 inactive/incomplete、7 format、8 image CRC。非法输入的包在外层测试可 PASS，
因为正确拒绝正是其期望行为。故意破坏 CPU/checker 的负例须保持原始 FAIL。

主机按包 stop-and-wait；坏 CRC 保持 next，重发同包。最近一个已接受 DATA 的
相同 seq/完整包 CRC 重试返回 DUP，既不重复写入也不前移 next；相同 seq 改内容
返回 sequence error。CRC32 是偶发传输错误检测，不构成鉴权或抗恶意碰撞保证。
BEGIN 用于中断后重新下载。包内任何字节等待超过 100000 CPU mcycle ticks，
session 中止、next=0；未完成镜像不执行，重新 BEGIN 可覆盖残留字节。
超长 DATA 头立即拒绝，解析器随后扫描 NXU1 重新同步。传输内容不用于 FPGA 配置。

RUN 校验前先 drain write-through D cache、执行 T09 D cache management 指令
`0x0000500f` 清除标签，并执行 `FENCE.I` 清除 I cache/串行化取指；随后从实际 RAM
读取全幅 CRC。跳转前再次维护可见性。普通 FENCE 不足以清除旧 I cache。
应用调用 ABI 为 RV32 ILP32，必须保留 callee-saved 寄存器/栈并可返回 ROM 下载循环；
连续 A/B 下载在同一次 CPU reset 之后、相同入口完成，不能靠复位掩盖 Cache 问题。

PRELOAD 与 PROTOCOL_BOOT 运行**同一个 Boot ELF**；只有显式模式/镜像初态不同。
PROTOCOL_BOOT 仅允许初始化 Boot ROM；应用的 64KiB 初态须全部为零，Boot SRAM
由软件清 BSS。禁止传入应用预加载参数。PRELOAD 是日常快速执行入口，记录其来源；
返回后仍可用协议重装。输出/签名区域从不预填期望值。

必测集合见 [配置](../../configs/t17-uart-boot.json)：合法几 KiB 包、坏包/镜像 CRC、
地址与入口边界、顺序错误、ACK 丢失后的重复重试、部分头/部分 DATA 超时、
中断恢复、同址 A/B 连续执行与 PRELOAD 共用启动。seed 1/7/19 覆盖 UART 字节间隙
和独立 I/D 内存反压；seed 1 精确复跑包含周期的 trace。VCD 全程覆盖 UART；
CSV 记录真实 AXI 和应用退休指令，独立核对字节、写入集合、签名和当前镜像指令。
板端时钟、DDR、烧录、CDC/时序和实物均不在本卡验收范围。
