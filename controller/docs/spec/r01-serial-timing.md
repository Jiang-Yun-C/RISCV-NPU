# R01 RX/MISO 时序合同

本合同记录实际 RTL 的时序关系及尚缺的硬件参数，机器入口为 `configs/r01-serial-timing.json`。状态 `INCOMPLETE_HARDWARE_PARAMETERS`，不授权 CDC/RDC 或板级时序通过。

已核对 T22、T23、T24 和 `project-scope.md`；后续卡尚为 DEFERRED。2026-10-09 用户确认实际标准板型为 **MES2L676-200HP（200Pro+）**。板卡版本、完整器件、原理图和引脚仍待 T22 核对，不能把原推荐系列或 PDS 的 PG2L100H FBG676 -6 工具探针器件替代实际完整料号。100 MHz、UART DIVISOR=64、SPI divider=249/3 来自仿真和固件合同，不是实板参数。现有外部域 SGDC 的 10 ns 仅为保守分析占位模型，不能用作 UART peer 或 SD 卡的真实时钟周期。

工作区同时新增了厂商资料目录 [logicmatrix/catalog.json](../sources/logicmatrix/catalog.json)，本轮仅引用，未修改该任务的资料。[厂商标准系列手册](https://szlogicmatrix.com/388.html)的机型表列出 200Pro+，主体电路说明针对 100Pro+，其中 27 MHz 系统参考和 125 MHz DDR 参考属于该文档机型；[MINI 教程](https://szlogicmatrix.com/forum-post/1281.html)另针对 200HP-MINI。它们不能直接决定本项目标准 200HP 实板的 PLL 输出、接口引脚或走线延迟。后续须按实板版号匹配原理图与工具工程，不能将示例的 27 MHz、100 MHz 或器件封装字符串拼成已确认时序参数。

已再次读取同步更新后的 T22–T24 卡及 [标准 200HP 板卡合同](../../board/mes2l676-200hp/board-contract.json)。文档目标 PG2L200H-6IFBB676、核心 D18/27 MHz、DDR N3/N2/125 MHz、UART B24/C24、SPI F19/H14/F18/H15 的共享板参考已按来源及页码归档到 `evidence/R01_CONSTRAINTS/r01-next-board-reference-v1/`，并由 JSON 的 documented_board_reference 引用。该参考与原件 PDF/文本 SHA 已核对；板卡合同明确 physical_identity_verified=false、PCB 版本/匹配 FDC 未冻结。因此这些值作为待核参考保存，hardware 中实际 oscillator/PLL/外部 min/max 时序参数继续为 null，不将 DDR 参考钟替代系统采样时钟。

UART RX 与系统时钟异步，输入只经 rx_meta、rx_sync 两级进入接收状态机。位间采样为 DIVISOR 个系统周期，起始位中点按整数 DIVISOR/2 计时。最终实现应约束同步级之间的正常时序和布局，并由真实 peer baud、容差、同步器延迟及整帧累计偏移计算接收裕量。不能把整个 RX 路径作为 false path。

SPI MISO 是主控 SCK 的源同步返回路径。timer 从 divider 到 0，包括零在内，每段为 divider+1 个 clk 周期；字节内部 SCK 周期为 2*(divider+1)。state=1 的 clk 边沿同时采 MISO 和更新 SCK 为高；state=2 更新 SCK 为低并移动 MOSI。采样所依赖的卡数据应在前一个 falling SCK 后返回。连续流最后一个 falling SCK 到下一字节 first rising SCK 至少为 2*(divider+1)+1 个系统周期；FIFO 反压可延长间隔。首字节缺少前一个 falling SCK，须独立核对 CS、卡首位有效时间与首采样关系。

约束应分实际支持的静态 divider 场景，表达系统 clk→输出 SCK→卡 tCO→MISO→采样寄存器的 max/min 路径。采样与输出 SCK 使用同一系统边沿，需计入输出、走线和输入传播时间；不能用任意独立 MISO 时钟签核或全局 false path 代替。JSON 中的 setup/hold 算式是待填参数的预算关系，须由实际器件/布局工具展开为时序约束并验证；没有填入猜测的延迟。

尚缺版号/完整料号、真实振荡器/PLL 时钟、UART peer baud/容差、卡型号/tCO、SCK 与 MISO 板级 min/max 延迟、FPGA 输出延迟及输入 setup/hold。license 缺失之外，该缺口独立阻止 R01.5 完整验收。T22 交付真实 board-contract 后应替换探索模型，再在同环境取得实际 CDC/RDC 及 I/O 时序报告。

2026-10-09 r01-width 再次核对当前板卡记录，归档于 `evidence/R01_CONSTRAINTS/r01-width-board-v2/`。合同新增 `jtag_device_identity_verified=true` 与只读JTAG/普通逻辑探针来源，但 `physical_identity_verified=false` 仍未关闭。独立 minimal_bist 源码描述的27MHz PLL输出和234周期/bit只属于该探针；不能把它作为R01 SoC系统时钟、接收DIVISOR或UART对端波特率/容差。旧 documented_board_reference 的合同SHA指向当时归档；新 board_evidence_reconciliation 单独保存当前合同SHA与来源，不覆写旧资料证据。

机器合同继续为 INCOMPLETE_HARDWARE_PARAMETERS / authorizes_signoff=false，增加实际 clock_uncertainty_ns、uart_receiver_divisor、sd_cs_to_first_data_min_ns/max_ns 缺口，仍为null。首bit预算应使用真实CS到数据界限和CS→首采样的实际间隔；稳态MISO路径继续按前一falling SCK的输出传播、卡tCO、回程传播及采样setup/hold展开。当前只验证RTL边沿关系，未获得实板数值约束或真实CDC/RDC报告；未使用整条MISO false path。

用户在本轮明确暂缓实际系统/串行参数追补，先继续其他R01修复与验证；缺项仍为null，未新增板端测量、未取得物理时序签核，不影响继续可执行的RTL/数值/功能/lint工作。
