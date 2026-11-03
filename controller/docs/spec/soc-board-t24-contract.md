2026-10-12 当前接续：用户已恢复板测，并询问改用 PDS。新实现采用全局 PDS2024.2/build178169 与 T24 新工具收据；静态方法改为 [PDS 时钟/复位与结构复核合同](../../configs/t24-pds-static.json)，SpyGlass 历史失败保留为旧方法证据。PDS 实际报告、逐路径结构复核和 VCS/实板复验合并验收，未覆盖项仍 OPEN。后文 rc3 与暂缓板测按历史离线范围理解。

2026-10-12 新增源版本：`nx_soc_core.ENABLE_TEST_CONTROL` 默认 0，关闭时为透传；验收镜像显式为 1，保留 MMIO `0x100000a0/a4/a8` 的通知模式、错误地址与迟到写地址控制。`nx_soc_test_response` 只注入传输响应，CPU/Coral 实际运算不变。四组同 T16 固件回归通过 739,100 项检查；关闭控制的兼容 smoke 通过。最终整核综合展开版本另验，旧 full 的冻结源不能代替此新增源版本的完整/物理资格。

Pango `GTP_CLKBUFGCE` 和原 `RstSync` 已用安装版模型通过 10,000 周期、65,840 项独立时序比较，包含 271 次异步复位断言、双下降沿 CE 延迟及 5,816 个完整脉冲。源版本绑定与范围见 [组件收据](../../evidence/T24_CLOCK_RESET/pango-gate-reset-20261012-v1/manifest.json)；板级 generated-clock、在途复位、PLL/PHY 和十项时序表仍须关闭。

实际 PDS Tcl 的查询对象为 `@tcicmdresult` 内部句柄，不能用 Tcl `llength/foreach` 当端点数量。采集改为实际 `.dmr` 的 Clock/Reset/CE 表及 `.rtr` 十表；[采集器验证](../../evidence/T24_PDS_REPORTS/t23-parser-plumbing-20261012-v1/manifest.json)仅消费 T23 旧实现来验证解析，不授予 T24 结构或物理资格。

2026-10-13 面积接续：新增可选 [Regfile](../../rtl/coral/pango/Regfile.v) FPGA 拓扑，保持八读/六写、碰撞 OR、x0、readSet、写掩码、scoreboard、复位和时钟延迟。49个状态寄存器与输出的全部已知输入状态转移证明通过4,402点，20,000周期差分通过1,240,000项；未知读地址仍不在转换资格中。[证明](../../evidence/T24_REGFILE_PROOF/regfile-bypass-transition-20261013-v3-state49/manifest.json)、[源级差分](../../evidence/T24_HOTSPOT_DIFF/regfile-bypass-diff-20261013-v1/manifest.json)。综合入口必须显式提供匹配的 `--regfile-qualification` 和 `--regfile-differential`，旧输入与失败证据不改写。

该新旁路已进入完整整核展开候选，同T16固件的三个control种子及seed1重放通过739,100项、2,004个输出；四份完整事务摘要均与旧硬件控制/原厂CE候选相同。独立native/数值复核通过，native另核对34,839,633项。[整核回归](../../evidence/T24_CORE_LOWERED/core-regfile-bypass-regression-20261013-v1/manifest.json)、[独立复核](../../evidence/T24_REVERIFY/core-regfile-bypass-native-review-20261013-v1/manifest.json)。同源连续head、五类检查器负例、整板预算与全部物理验收仍OPEN。

[分银行ALU保留站](../../rtl/coral/pango/nx_coral_banked_rs_fifo.sv)为独立候选：3入/2出/8深、597位；只省去原站未连接的全表监视端口，不更改指令或计算单元。消费端口对照为8,407→3,938 LUT、4,789→20 FF、34 DRM36K；源级和实际PDS2024 DRM/FF/LUT网表各通过20,000周期、440,000项及独立模型检查。[源级/资源](../../evidence/T24_BANKED_FIFO/alu-rs-banked-20261013-v4-direct-write/manifest.json)、[实际映射模型](../../evidence/T24_BANKED_FIFO_MAPPED/alu-rs-banked-mapped-20261013-v2-grs/manifest.json)。`clear`仅清指针/计数，保留存储并接受当拍写；初版错误清存储的失败已保存。此模板尚未集成进最终整核，未转授MUL/FALU、在途复位、门控协议或板端资格。

未选择的共享LSU跨步候选虽从253降至1 APM，却从113,881增加到127,766 LUT；FIFO优先译码同样扩大面积。全部测量与失败归档保留。最后完整整核预算仍为335,168 LUT/159,800，尚未计PHY及外围；这些局部收益不代表已解决面积，不推进超预算候选的布局布线或下载，T24继续ACTIVE、Coral继续SIM_SELECTED。

# T24 共用计算核的离线合同

本轮按用户 2026-10-11 的指示继续暂缓板测。目标仍为标准 MES2L676-200HP/200Pro+ V1.2，PG2L200H/FBB676/-6；工具保持 PDS 2022.2-rc3 build 113398。T24 正式状态 ACTIVE，Coral 仍为 SIM_SELECTED。板级合同与原生 HMIC1.10 的物理资格由 T22/T23 独立交付。

## 共用核与输入身份

`rtl/soc/nx_soc_core.sv` 实例化实际 T09 hard CPU、实际 RvvCoreMiniAxi、原有 bridge/guard/共享通道仲裁及新增 DDR fabric。`tests/board_soc/tb_core_body.svh` 直接实例化该核，外部数字模型提供本地存储、timer、ROM 与 native DDR；影子接口只观测，不驱动产品核。故障矩阵在 TB 中强制通知屏蔽/延迟、AXI 错误与迟到 B，不替换 CPU/Coral 运算或初始化结果。

`configs/t24-soc-board.json` 复制 T16 的正常/故障矩阵。ELF、Coral 微程序、fixture 数据、黄金数组和地址消费 `evidence/T16/acceptance-20261007-v3` 的已验收字节；只重写归档内文件路径。full 必须含连续 151936 行 head、三个 control 种子及 seed1 重放、五类门禁负例，短回归不能替代 full。

## 逻辑总线边界

CPU I/D 为 AXI32/ID1，Coral 为 AXI128/ID6。每个端口分别保持读/写目的地，字节范围 `[0x80000000,0xc0000000)` 进入 DDR，其余进入独立本地端口。六个读/写请求轮询，在 VALID 前锁定选择，单 native 事务在途。CPU 数据/strobe 按当前地址在 128 位总线中移位，读返回反向移位；Vex 缓存的 SIZE2 单拍 partial store 按 32 位字边界规范化地址，保留原 WSTRB。

写数据依 AWLEN 收齐，错误 WLAST 仍按长度排空。每个主口暂存一个 B 响应，Coral 保持 B 背压时仍允许其他主口和 CPU 本地访问推进。读在 RLAST 接收前保持选择。

T23 适配器继续负责 AXI128 到 HMIC 256 位/32 字节掩码/28 位四字节 word address，native ID 固定 0；native burst 不超过 16 拍且不跨 4KiB column。B OKAY 仍要求掩码读回一致。适配器默认写后等待 1024 周期；本轮 core 候选显式采用 8 周期，在数字模型及保护控制器加数字 DFI 中复验，尚无该参数实板资格。core 假定 native 用户口与 CPU 同域；实际目标频率 125MHz 不是本轮已验收 Fmax。

## RAM 与综合转换

`rtl/coral/pango/Sram.v` 用可综合字节写使能数组和寄存读地址替代 DPI 存储，同一源码用于 VCS 和 PDS 输入。TCM 仍由实际 CPU 上传/读回，未做全局零初始化。

rc3 原生前端不能接受完整 Coral 的 package/常量函数/接口展开。隔离工具 sv2v v0.0.13 与 Yosys 0.23 用于整体转换和参数/过程展开；PDS 负责器件映射。下载包、工具/sysroot 哈希、原输入、转换结果、移除的仿真诊断与 VRF 写合并规范化均另存，不改变全局安装。转换不能自行授予功能资格；fabric 有独立定向复验，VRF 规范化需 differential 与独立模型复验，完整 Coral 转换仍须实际固件复验。

写端口合并经过 [512×128 SRAM 三方比较及 DRM 推断](../../evidence/T24_SRAM/sram-ports-20261011-v1/manifest.json)：原数组、合并模板和独立字节模型共 1,318,962 项比较，包括未初始化字节、掩码、同地址读写及关闭使能。单实例为 2 DRM36K、6 LUT、10 FF。综合副本中的五个同深度 SRAM 使用该冻结模板；严格核对原源码哈希、端口/深度及资格归档，不修改共用核联测的原 SRAM。整套转换还须消费同固件/fixture 完成独立短矩阵。

生成 CPU 的 `InstructionCache.io_cpu_fetch_data`、`DataCache.io_cpu_writesPending` 与 `DataCache.io_cpu_writeBack_exclusiveOk` 没有实现，连接到的三个内部网也没有消费者。转换副本只移除这三个空端口及空连接，遇到额外驱动/扇出即拒绝转换；不赋默认值、不关闭 `check -assert`，实际联测 CPU 不改动。每轮保存删除行和前后哈希，CPU 初始化 `.bin` 单独归档。

## 明确保留的 OPEN 关口

- 本轮 init 为数字延迟，未证明实际训练、PLL/PHY 时钟复位或上电失败通知。local/ROM/timer 由测试环境提供；可下载板级外围封装与加载协议仍须连接并验收。
- Coral 当前 ClockGate 仍为上游通用 latch 门控实现，尚未完成 Pango 全局时钟使能原语及其延迟/复位资格。
- lint 的未审结告警、缺少许可的 CDC/RDC、完整 core/DDR PHY 的资源映射、布局布线、setup/hold、DRC 与约束覆盖必须独立关闭；组件 SNR 不能替代这些报告。
- 不复用 v7 的 1GiB/掩码/一小时实板结果为本轮新 SoC 背书，不下载旧 ADF，不升级 FPGA_QUALIFIED。
