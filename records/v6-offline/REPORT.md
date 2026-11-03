# Demo V6 CPU异常/中断、AI应用与原生片上分析仪离线交付

本轮已完成独立候选修改、有界数字验证、原生Fabric调试核、新PDS完整实现、位流与配套离线资产。**应用端到端验收仍OPEN**：完整24层Qwen在新CPU/NPU生产配置中的推理+灯效+取消+READY并发整请求未执行；本轮分别执行真实模型主机验证与真实CPU/NPU局部集成，不能把二者拼成一次完整FPGA实时模型运行。所有实板/光学抓取均NOT_RUN，production_GO=false。

## 身份与物理边界

- 新CID：`3ebbf449cb622e28baa59e02e02da20ba79a4a4b03d3278aacfa650ecbcb413a`，1046个完整文件，`variants/demo_v6_irq_20261102_v1/source`。
- 新调试交付EID：`8ef3ff0698423c55cb41c06fce036b6e1a0a8bf0d06bfbac48a602b96f517451`；父版Demo V5 CID `20a0545a394a86a5df98d8d91aa714bbb7870fbe79c80ba0656b5a187ab67266`完整复制，27个变更文件/8个新增文件。补丁重建逐文件与新CID一致。
- 当前物理CoreMark CID `78f2636b1cfb5619b3b5932a02443e19d9e0536b2c6fea097bc6a12b8089fc36`保持；本轮物理操作0，累计配置9/尝试10/板端模型装载触发8均未增加。未打开串口、下载、写SD/Flash/NVM、reset/reload或板端装载模型。其他独立对话的RTL任务不由本轮接管/重启。
- `current/`、CoreMark及所有父版/旧报告/失败收据保持。交付为**DEBUG_FABRIC_260x1024_125MHz_UART115200**；新评测位流NOT_BUILT，短仿真不是新的实板CoreMark成绩。

## CPU明确缺口与覆盖

D AXI B响应现在端到端进入缓存/提交逻辑；store保持在WB等待自己的B，失败store不正常退休、不更新命中缓存、不放行年轻store。SLVERR/DECERR给出cause7、正确store PC及有效地址；不是退休后补异步标志。正常成功store在AW时遇到MEIP、B再延31周期的用例也验证了B→退休→IRQ、单次副作用与MRET继续执行。W先于AW和AW先于W均实际执行，错误不污染随后事务；错误从设备拒绝写入，CPU不声称回滚任意AXI从设备内部的部分副作用。

17个异常实例覆盖必选cause0/1/2/3/4/5/6/7/11、FSW/FLW、非法指令/未实现与只读CSR、ECALL/EBREAK、取指与数据错误/未对齐、MRET。独立检查从实际ELF符号/编码及CPU退休/总线事件绑定PC/cause/mtval；同步异常优先于同时pending的中断，MEI>MSI>MTI，WFI在全局MIE关闭而个别源pending时仍唤醒。信息CSR、MSTATUS[H]、MIE/MIP设备所有权、direct-only MTVEC、MEPC低2位、MCAUSE/MTVAL、MCYCLE/MINSTRET读写/64位回卷和MCOUNTINHIBIT CY/IR、FCSR及CSRRS/CSRRC已测。

机器态合同依据[RISC-V Machine-Level ISA](https://docs.riscv.org/reference/isa/priv/machine.html)及[CSR分配](https://docs.riscv.org/reference/isa/priv/priv-csrs.html)。RV32IMF、M-only、IALIGN32；未扩展S/U/MMU/PMP/NMI，也不声称完整RISC-V符合性认证。SoC MSIP输入仍绑0，不能把CPU输入能力写成已连接的软件中断设备。

实际生成RTL核对各16KiB、两路、32B行、每组LRU及256项BTB；未重做已有缓存/预测。固定上游+补丁001–003+GenT09新重建，所选RTL/RF初始化逐字节一致；实际环境sbt1.6.0/Temurin Java8/Spinal1.13，源内历史README的Java17说明不代表本轮工具身份。五项真实CPU Cache/BTB/FENCE.I/自修改负载和两套官方CRC通过。相同10迭代短CoreMark父CPU→新CPU：performance 5424301→5705100周期（+5.176685%），validation 5443484→5722189（+5.119975%）；包含精确store等待等新机制代价，不折算为物理成绩。

完整要求矩阵见[REQUIREMENTS_MATRIX.md](REQUIREMENTS_MATRIX.md)，生产调度说明见[INTERRUPT_APPLICATION_DESIGN.md](INTERRUPT_APPLICATION_DESIGN.md)。

## 应用中断与AI灯控数字结果

NPU完成/故障经真实bridge MEIP，ISR只mask+登记；主流程验证acquire后消费，原session/epoch、共享内存可见性、native1024、ACK/owner与缓冲寿命不变。UART实际RTL按DIVISOR1085生产比率输入完整25字节取消行；ISR最多64B/次、8192B环，解析/模型/执行留在主流程。硬件FIFO/W1C优先、环溢出毒化/换行恢复、head/tail与毫秒回卷、事件早于wait、合并/重复都另有真实CPU/组件用例并明确替身范围。mtime/compare连接MTIP，1ms板端调度；不由主机逐次开关。

七个真实生产CPU+SoC/CE/SFU局部运行均通过，单次上限240s，累计主机仿真1214.839606s。DDR为行为时序/有限合成权重夹具，原native1024完成有效。三组成对输出/实际DMA字节/共享FP顺序/owner/ACK/排空逐位及独立数值检查通过：

| 局部API | IRQ关闭周期 | IRQ开启周期 | 增加 | 等待状态轮询次数 |
|---|---:|---:|---:|---:|
| linear M4/K896/N8 | 933598 | 1230596 | +31.812193% | 2486→7 |
| attention M1/len33/D64 | 5354570 | 5871074 | +9.646041% | 10443→11 |
| SwiGLU→down M4/K4864/N8 | 5772636 | 6170273 | +6.888309% | 44638→45 |

IRQ开启臂同时承担实际UART接收和LED定时任务，以上不是孤立ISR开销，也不能与CoreMark百分比相加。轮询减少99.718%/99.895%/99.899%，NPU通知不是全靠轮询。NPU IRQ→CPU trap最大3267周期、→软件登记最大6694周期；C handler内部最大13184周期，不含入口/退出。最大观察timer迟到216903周期，含夹具UART串行诊断阻塞；稳态10ms灯效间隔相对1250000周期最大偏差2001周期。这些是数字计数，未冒充实板实时保证。

数值溢出NPU用例：有限操作数接受后真实SFU失败/IRQ→CPU→主流程安全CE session恢复→下一次真实PV的64个word正确；不是FPGA reset/reload。正常/错误用例终态都继续推进时间核验全部响应及owner/native排空。局部峰栈9920B、4096B guard通过；80B入口保存16个caller GPR、FS关闭/恢复，整数ISR反汇编及保守额外栈128B通过。新链接ELF文件+4224B、PT_LOAD内存+12528B，包含8192B环；完整生产动态最大栈UNKNOWN。

完整Qwen24层W8用本轮新编译主机生产C实际推理：自然语言“打开灯。”/“关闭灯。”得到合法JSON/EOS，无语义结果缓存；普通问答不产生LED授权。确切新输出作为RV32解析/MMIO边界输入，实际CPU每个动作一次写入、正确mask0x2d及值读回，未知动作拒绝；**RV32段是本轮新输出的边界重放，不能称为同一次RV32/NPU实时整模型推理**。完整模型主机prefill/decode取消均产生匹配ABORT、清KV，随后新的完整真实请求再次成功；没有强制ID。生产服务26例ABORT/REQUEST_END/READY及后续请求通过，使用合成2块模型/受控ID/MMIO；IRQ-on主机通知钩子替身与IRQ-off的26份协议逐字节一致，实际ISR证据来自另行CPU/RTL测试。

`:blink MASK PERIOD_MS EDGES`参数为十进制，计数0连续；有限计数是到期提交槽数，末槽强制OFF，可能不是同数目的光学边沿。READY时`:blinkstop`停止活动mask并保留所有权；新合法direct/model提交先取消旧调度，旧tick不会覆盖新OFF。忙时普通命令不插队，按现有匹配`:cancel <session>`安全检查点结束后再发送后续灯控；取消/普通问答自身不授权新动作。已有快捷/缓存来源标记保留，不能作为本轮实时模型证据。

## 实际片上分析仪与PDS

采用安装版PDS2024.2 build178169 Fabric Inserter/Debugger及原生DebugCore/JTAG hub，实际插核、device map与布线已完成；不是mark_debug空壳或Vivado ILA。260位、1024深度、256预触发、core_clk125MHz；四个原生触发单元对应LED写、NPU完成/故障IRQ、匹配UART取消、store fault。通道表、匹配FIC、符号表、Tcl模板见[debug-delivery](debug-delivery/README.md)。模板只通过语法/安装版手册检查，硬件抓取NOT_RUN。TU4存储资格使样本不等间隔，不能按每点8ns推算长链路延迟；直接功能网采样额外延迟0周期，不依赖源内未使用的256位观测寄存器。

完整PDS实际选择seed12，目标PG2L200H/FBB676/-6、系统/CPU/CE125MHz，87脚逐项匹配父版；未降频或放宽功能约束。新核自身ADS 1199 LUT/2702 FF/7.5 DRM36K等价/0 APM（这是综合口径）；最终routed **72889 LUT / 50068 FF / 137 DRM物理site / 43 APM**，通过原85000/73800/140/57预算。零latch、零未布线、零过用。

| 时序表 | 最小slack ns | 判定 |
|---|---:|---|
| Setup/Slow | 0.000 | PASS |
| Hold/Slow | 0.062 | PASS |
| Recovery/Slow | 0.980 | PASS |
| Removal/Slow | 0.323 | PASS |
| Minimum Pulse Width/Slow | 0.035 | PASS |
| Setup/Fast | 2.878 | PASS |
| Hold/Fast | 0.041 | PASS |
| Recovery/Fast | 3.744 | PASS |
| Removal/Fast | 0.095 | PASS |
| Minimum Pulse Width/Fast | 0.035 | PASS |

所有表TNS/失败端点为0，文本/XML包括长JTAG时钟名逐项一致。Setup/Slow 0.000ns仅表示报告精度下通过，不能宣称有额外裕量/Fmax。原生IP声明JTAG50/100ns时钟，系统ddrphy_sysclk仍8ns。no_clock=0、无部分约束/组合环/latch；原有1个virtual clock、36输入与81输出未指定delay的外部端口列表逐项保持，厂商DDR/异步端口合同与全面生产PHY资格不因此闭合；独立postroute DRC/CDC/RDC未运行，不能升级生产GO。

从同一routed ADF新导出98MB原生功能网表，未执行门级仿真。独立解码两份ROM读副本各16个DRM、16384个word，全部等于新认证ROM。随后从该ADF生成新压缩sbit（SHA256 `c4b5c641860d91f6c9aecb16392cc996428a63d26a5bc6d544b36a98f34ff41e`），没有下载。唯一离线调试EID见上；新评测位流未构建。

## 启动、介质与失败证据

新应用SHA256 `6673a46f2c7bd4d764703ad4c803e419f3d84dbcf92e15fcb05873930b05b62d`；ROM SHA256 `f375d69e73116258459d8f2594bf4967220e0f6b1353a39a86ac68c7641cdde9`；SD SHA256 `cd8cbdda5d97a6d450375e96d47468e0d1c89422eed3edfbb13be2429fdd230d`。ROM仅改变新应用32字节信任摘要，其余字节与父loader相同。应用5275888B、模型536731456B，新模型起点LBA10306、完整镜像542008320B；从实际大小重新派生。精确认证C解析验证467个内存span，旧ROM拒绝新应用、DDR破坏/扇区CRC负例通过。仅在主机生成/审计镜像，未写卡，完整新CPU+SPI认证启动未执行。

所有真实失败/更正保留：生成器连接/类型与仿真编译准备失败、夹具UART sink/mask错误、主机头文件/协议检查器错误、旧观测网无负载导致Fabric不可选、原生MatchUnit需完整连线后设置、power-on参数/Qt完成标记/名称解析问题。最终配置由原生工具保存并返回0。PnR只执行本次新实现一次多seed流程；收敛后工具正常终止其它seed。首个自动复核器引用错误helper目录，随后旧解析器漏掉换行的长JTAG时钟名，均阻止bitgen并保留负收据；新解析器从文本clock summary恢复完整标签、与XML全字段相等，并拒绝三种标签篡改。仅对同一routed ADF接续复核/导出/bitgen，没有重复PnR或重写历史报告。

## 交付与只读复验

完整源码/补丁、ELF/bin、新认证ROM、SD镜像、routed ADF、原生调试网表、sbit/FIC/探针/四触发及报告集中于`exports/demo-v6-irq-offline-20261102-v1/`；完整原始轨迹和全部失败收据保留在本固定evidence目录。工具安装/许可证不随包复制；包不声称替代全部原始验证现场。项目只读入口`make demo-v6-irq-verify`；便携包运行`python3 -B verify_delivery.py`，不会启动编译/仿真/EDA或硬件。不要重启已完成run脚本。

下一阶段具体恢复/授权边界、实板中断、原生波形及光学LED计划见[NEXT_BOARD_PLAN.md](NEXT_BOARD_PLAN.md)。本轮NOT_RUN/UNKNOWN完整清单见VALIDATION；应用端到端验收仍OPEN。
