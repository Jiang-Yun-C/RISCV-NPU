# PDS 与标准 MES2L676-200HP 资料交接

核对日期：2026-10-10。标准 **MES2L676-200HP（200Pro+）V1.2** 原始ZIP、已解压原件及关键路径见下节。保留全局rc3/安装内HMIC1.3，项目内原厂原生200H/HMIC1.10生成源在rc3重建；native110-v7已通过校准、1GiB/32byte masks和3664.812秒零错误压力。完整PHY/一般适配器、芯片丝印、物理按键和冷启动仍待验收。旧1.3窗口按历史记录理解。

可复用 skill：[pango-pds](/home/Jiang/.codex/skills/pango-pds/SKILL.md)。工具入口继续按 [PDS 调用合同](pds-toolchain.md)；板型与待核字段见 [板卡合同](../../board/mes2l676-200hp/board-contract.json)。所有公开原件、URL、下载日期、SHA256、抽取文本与本机手册身份见 [资料目录](../sources/logicmatrix/catalog.json)。PDF页码均为**从1开始的物理页**，不能直接当正文印刷页码。

## 200H资料包位置与关键原件

T22–T33均已在卡片中登记本节和[可机读路径/hash清单](../sources/logicmatrix/standard-200hp-materials.json)，任务登记表的`input_vendor_materials`与`vendor_reference_ids`指定各卡对照对象。现有原件无需重新寻找下载入口。

- **原始完整ZIP**：[/home/Jiang/RISCV+NPU/盘古200Pro+开发板（MES2L676-200HP）配套资料.zip](../../盘古200Pro+开发板（MES2L676-200HP）配套资料.zip)，3334170032字节，SHA256 `d5679e8fd24fd96b97f91089dd0d5c2903bfc46e9ca92603d8754ce8b2004124`。
- **已解压原厂目录**：[/home/Jiang/RISCV+NPU/build/T22_VENDOR/standard-200pro-20261010-v1/vendor](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/)。本次按需提取563文件，所选条目CRC验证通过；原ZIP共10,545条目，RAM/FIFO及其他未提取demo继续保存在ZIP。
- **导入/恢复依据**：[archive-import.json](../../evidence/T22_VENDOR/standard-200pro-20261010-v1/archive-import.json)保存ZIP成员名、提取前缀、大小、CRC和各文件SHA256。原件只读使用，重新提取到新目录，再核hash；不要覆盖本轮原件或冻结证据。

原厂DDR外层工程目录：

`/home/Jiang/RISCV+NPU/build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_9_ddr3_test/2_9_ddr3_test/ddr3_test`

原生200H/HMIC1.10生成源目录（下面简写`DDR_IP/`）：

`/home/Jiang/RISCV+NPU/build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_9_ddr3_test/2_9_ddr3_test/ddr3_test/ipcore/ddr3_test`

实际`generate.log`记录PDS2022.2-SP6.4/build146967、HMIC1.10、PG2L200H/FBB676/-6；两份原厂`.pds`和`.idf`用于确认目标/参数/源清单。包内旧100H缓存和旧SP6.4数据库分别保留，本项目在rc3从生成源重建新数据库。

| 对照内容 | 可直接打开的本地原件 | 用途 |
|---|---|---|
| 专用硬件手册 | [200HP V1.2手册](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/1_Demo_document/实验例程说明篇/MES2L676-200HP硬件使用手册_v1.2.pdf) | 物理页11供电、12–13时钟、14–17 DDR、34 UART、40–43 KEY/LED/EEPROM/SD |
| 底板原理图 | [3_Hardware/…/MES2L676-BASE-V1.2-供客户做底板.sch](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/3_Hardware/MES2L676底板设计资料/MES2L676-BASE-V1.2-供客户做底板.sch) | 外设/连接器/电平对照 |
| 底板PCB | [3_Hardware/…/MES2L676-BASE-V1.2-供客户做底板.pcb](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/3_Hardware/MES2L676底板设计资料/MES2L676-BASE-V1.2-供客户做底板.pcb) | 底板布线/布局参考 |
| 核心板点位 | [3_Hardware/点位图/MES2L676-CORE-V1.2-点位图.pdf](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/3_Hardware/点位图/MES2L676-CORE-V1.2-点位图.pdf) | 核心板元件/连接位置 |
| 底板点位 | [3_Hardware/点位图/MES2L676-BASE-V1.2-点位图.pdf](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/3_Hardware/点位图/MES2L676-BASE-V1.2-点位图.pdf) | 跳线/连接器/外设位置 |
| DDR外层工程 | [ddr3_test/ddr3_test.pds](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_9_ddr3_test/2_9_ddr3_test/ddr3_test/ddr3_test.pds) | 原厂200H顶层工程来源 |
| DDR生成源清单 | [DDR_IP/pnr/ddr3_test.pds](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_9_ddr3_test/2_9_ddr3_test/ddr3_test/ipcore/ddr3_test/pnr/ddr3_test.pds) | 原厂92源的example工程 |
| DDR约束 | [DDR_IP/pnr/ddr_test.fdc](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_9_ddr3_test/2_9_ddr3_test/ddr3_test/ipcore/ddr3_test/pnr/ddr_test.fdc) | pin、I/O电平、宏位置；有效项目FDC另对照 |
| DDR生成配置 | [DDR_IP/ddr3_test.idf](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_9_ddr3_test/2_9_ddr3_test/ddr3_test/ipcore/ddr3_test/ddr3_test.idf) | 容量/row/column/bank/速率和接口参数 |
| 用户口wrapper | [DDR_IP/ddr3_test.v](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_9_ddr3_test/2_9_ddr3_test/ddr3_test/ipcore/ddr3_test/ddr3_test.v) | 地址/数据/握手实际端口 |
| PHY wrapper | [DDR_IP/ddr3_test_ddrphy_top.v](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_9_ddr3_test/2_9_ddr3_test/ddr3_test/ipcore/ddr3_test/ddr3_test_ddrphy_top.v) | DQ/DQS/DM、IOCLK、PLL/CPD和复位 |
| 原厂生成日志 | [DDR_IP/generate.log](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_9_ddr3_test/2_9_ddr3_test/ddr3_test/ipcore/ddr3_test/generate.log) | 实际器件、生成器/IP与来源版本 |
| 原厂示例顶层 | [DDR_IP/example_design/rtl/test_ddr.v](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_9_ddr3_test/2_9_ddr3_test/ddr3_test/ipcore/ddr3_test/example_design/rtl/test_ddr.v) | 原厂BIST/UART与项目替换顶层的差异 |
| HMIC1.10包 | [6_IP_setup_packet/PG2L/DDR3/ips2l_hmic_s_v1_10.iar](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/6_IP_setup_packet/PG2L/DDR3/ips2l_hmic_s_v1_10.iar) | 来源/独立安装对照；现有路径直接复用生成源 |
| 随包HMIC手册 | [6_IP_setup_packet/PG2L/DDR3/UG042003_HMIC_S_IP.pdf](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/6_IP_setup_packet/PG2L/DDR3/UG042003_HMIC_S_IP.pdf) | 版本读正文；与公开V1.14手册分别记录 |
| PLL工程 | [2_Demo/2_5_pll_test/…/pll_test.pds](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_5_pll_test/2_5_pll_test/3_5_pll_test/pll_test.pds) | PLL用法；实际27MHz和125MHz按工程核对 |
| 按键/LED约束 | [2_Demo/2_7_key_led_test/…/source/key_led_test.fdc](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_7_key_led_test/2_7_key_led_test/source/key_led_test.fdc) | 物理复位/LED参考，KEY工程见清单 |
| UART约束 | [2_Demo/2_8_uart_test/…/uart_test.fdc](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/2_Demo/2_8_uart_test/2_8_uart_test/uart_test.fdc) | UART参考，UART工程见清单；C24/B24诊断用途另核 |
| 下载/固化指南 | [1_Demo_document/工具使用篇/05_FPGA&CPLD的下载与固化_v1.1.pdf](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/1_Demo_document/工具使用篇/05_FPGA&CPLD的下载与固化_v1.1.pdf) | 区分CRAM JTAG和Flash持久配置；实际Flash/冷启动另验 |

硬件手册另有便于引用的[仓库副本](../sources/logicmatrix/standard-200hp-hardware-v1.2.pdf)，与包内原件SHA相同。`3_Hardware`已取得底板SCH/PCB和核心/底板点位图，独立完整核心板SCH仍未定位；DDR电路可先对照专用200HP手册内嵌图，并记录未覆盖项。

## 原厂资料与通过工程的对照顺序

1. 用专用200HP手册、实板合同和有效pad表确定PCB/引脚/电平；共享100HP教程只接收明确匹配的部分，MINI资料不作标准200HP合同。
2. 用原厂`generate.log`、200H `.pds`、`.idf`和wrapper确定实际IP配置与源版本，不能仅看目录名。随包1.3–1.15文件是资料库存，默认不安装或替换已通过的1.10源。
3. 与[v7冻结输入](../../evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/inputs/build/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/)中的`sources/`、项目BIST/UART/observer、`native110.fdc`和`flow.tcl`逐项对照；原厂FDC与[实际通过的v7 FDC](../../evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/inputs/build/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/native110.fdc)分开保存。新工程用相对/重写后的绝对路径，重新列hash和差异；91份原厂源未改的基线可核验。
4. 通过范围引用[v7清单](../../evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/manifest.json)和[同镜像压力清单](../../evidence/T23_NATIVE/native110-full1g-stress-20261010-v1/manifest.json)，执行步骤见[已验证工程路径](200pro-verified-pds-path.md)。新SoC/应用/优化镜像另作受影响时序与实板复验。

## 历史1.3移植与资料导入窗口（2026-10-10）

[2026-10-10状态](../../evidence/T22_VENDOR/standard-200pro-20261010-v1/status.json)：用户下载的标准200Pro+ ZIP SHA256为`d5679e8fd24fd96b97f91089dd0d5c2903bfc46e9ca92603d8754ce8b2004124`，选择563文件CRC验证通过；附带安装程序未运行。专用200HP手册V1.2及原生200H/HMIC1.10示例，与用户报告PCB V1.2对照，73个DDR/参考时钟引脚全部一致。核心/底板点位图和底板SCH/PCB已取得，未找到独立完整核心板SCH；手册内嵌DDR电路可复核。

rc3＋HMIC1.3移植v7在200H目标编译、ADS、映射、PnR、十组时序和位流生成通过，有限复位传播约束已审查，使用pre-silicon模型。实际DDR100kHz CRAM下载进行中。板载CP2102安装匹配驱动后为COM10、Code0；COM9为JTAG适配器串口。当前仍不能据离线时序或串口驱动关闭DDR验收。详细边界见[平台报告](../reports/platform-feasibility.md)。

[昨日IP/只读记录](../../evidence/T22_VERIFY/board-ip-20261009-v1/manifest.json)保留原生HMIC1.3生成200H拒绝及100H对照，不因移植结果修改安装支持列表。[昨日普通PLL/DRM/LED板端通过](../../evidence/T22_ADAPT/standard-200pro-20261009-v1/manifest.json)保留，今日下载前DONE0，不能假设昨日易失配置仍有效。

## 历史工具探针与官方版本边界

本机 PDS **2022.2-rc3/build113398** 的 shell/ADS 再检查为 PASS：[证据](../../evidence/PDS_TOOLCHAIN/skill-research-20261009-v1/manifest.json)。这次还实跑了十条命令帮助：[记录](../../evidence/PDS_BOARD_DOCS/20261009-v1/pds-command-help.log)。探针目标仍为PG2L100H，只证明工具就绪。

官方 **UG042003 HMIC_S V1.14 §2.3.1.1，PDF页14（正文13）要求PG2L200H使用PDS 2022.2-SP1.2或以上**。当前rc3不能视作满足这个最低版本。本机 `iplist.xml` 标识HMIC_S1.7但未列200H；实际IP `index.xml` 为1.3、仅列100H/FBG676。原XML已保存，见目录中的 `PDS-IPLIST`、`PDS-DDR-INDEX`。按用户要求先验证rc3＋1.3移植实验的实际实现与板端结果，其他SP/IP只作独立对照；不凭支持列表要求升级。本次普通PLL/DRM/LED已在板上通过，DDR仍未验收。

用户随后要求rc3可用就保留。新增 [200H预检查](../../evidence/T22_PRECHECK/windows-rc3-20261009-v1/manifest.json)已通过PG2L200H/FBB676/-6普通逻辑的编译、ADS、映射、PnR、时序报告和位流生成。Windows经`ATK-HS-V2-CMSIS-DAP`的HID接口三次读到`0x10603899`，确认PG2L200H连接；COM9属于同一适配器的串口。当前保留rc3，普通逻辑预检查与HMIC_S最低版本分别记录。探针IO由工具自动分配，生成位流未下载；正式板级时序/DRC、原生Fabric下载路径和DDR仍未验收。

取得的原生标准200HP例程同样使用 **PDS2022.2-SP6.4/HMIC_S1.10**。包内旧100H缓存脚本和20ns普通时钟约束已记录；当前移植以实际27MHz和200H器件重实现。新手册提供VCS示例，但不代表本机VCS X-2025.06已与实际生成库验证兼容。

## 可直接查阅的资料

| ID／资料 | 来源与本地原件 | 定位与用途 |
|---|---|---|
| LM-HW-200HP 标准200HP硬件V1.2 | [资料包入口](https://szlogicmatrix.com/forum-post/410.html)／[PDF](../sources/logicmatrix/standard-200hp-hardware-v1.2.pdf) | 专用200HP；11供电、12–13时钟、14–17 DDR、34 UART、40–43 KEY/LED/EEPROM/SD、45备用时钟；本次板级主要来源 |
| LM-HW-STD 标准676硬件V1.2 | [发布页](https://szlogicmatrix.com/388.html)／[PDF](../sources/logicmatrix/standard-676-hardware-v1.2.pdf) | 主要为100HP，PDF页8列200Pro+，页22–25时钟/DDR，43–44UART，51–53LED/EEPROM/SD，55–59FMC/供电；部分FMC管脚专门标200H |
| LM-LAB-STD 标准676通用实验V1.2 | [发布页](https://szlogicmatrix.com/452.html)／[PDF](../sources/logicmatrix/standard-676-general-experiments.pdf) | 第3章厂商仿真，第5章PLL、第6章RAM/FIFO、第8章UART/Fabric、第9章DDR；目录PDF页4–6，DDR配置从页137开始 |
| LM-PDS PDS快速使用 | [发布页](https://szlogicmatrix.com/827.html)／[PDF](../sources/logicmatrix/pds-quick-start.pdf) | 页3–15：GUI工程、编译综合、约束和实现；Compa示例不作为200HP参数 |
| LM-IP IP安装/用户指南 | [发布页](https://szlogicmatrix.com/821.html)／[PDF](../sources/logicmatrix/ip-install-guide.pdf) | 页1–4：IPC Update/Add Packages/Install、选择IP及浏览指南 |
| LM-CONFIG 下载与固化V1.1 | [发布页](https://szlogicmatrix.com/818.html)／[PDF](../sources/logicmatrix/fpga-download-guide.pdf) | 页1–2 JTAG/.sbit；3–9外部Flash识别、转换与固化；10–11为CPLD，不能套用 |
| LM-SIM PDS/Modelsim | [发布页](https://szlogicmatrix.com/830.html)／[PDF](../sources/logicmatrix/pds-modelsim-guide.pdf) | 厂商支持工具的参考入口；项目VCS+cocotb保持独立验收 |
| LM-FMC MES-FMC-LPC-IO | [发布页](https://szlogicmatrix.com/1153.html)／[PDF](../sources/logicmatrix/fmc-io-hardware.pdf) | 页6–8 J2/J3接线、11 VADJ；用于标准板接实际传感器 |
| PG-DS Logos2 DS04001 V2.1 | [官方PDF](https://www.pangomicro.com/en/uploads/13964872_1729131653.pdf)／[本地PDF](../sources/logicmatrix/logos2-datasheet-v2.1.pdf) | PDF页12（正文11）：器件资源和封装资源，作为T24/T30分母 |
| PG-PIN PG2L200H FBB676 PK04008 V1.0 | [官方PDF](https://www.pangomicro.com/en/uploads/34165729_1729132019.pdf)／[本地PDF](../sources/logicmatrix/pg2l200h-fbb676-pinout-v1.0.pdf) | 封装、400用户IO及管脚表；与板级网名交叉核对，不提供PCB连线 |
| PG-PRODUCT Logos2产品页 | [官网](https://www.pangomicro.com/product/logos_family/195.html)／[快照](../sources/logicmatrix/pango-logos2.html) | PG2L200H/FBB676；备注3明确FBG676/FBB676管脚兼容 |
| PG-DDR HMIC_S UG042003 V1.14 | [官方PDF](https://www.pangomicro.com/en/uploads/17503246_1729499157.pdf)／[本地PDF](../sources/logicmatrix/hmic-s-guide-v1.14.pdf) | 12支持表、14工具下限、25–27仿真/实现、35–37精简AXI差异、63地址/时钟约束 |

本机主命令以 `PDS_HOME/doc/Pango_Design_Suite_User_Guide.pdf` 第5/9章和实际 `-help` 为准。FDC/UCE见 `User_Constraint_Editor_User_Guide.pdf`，时序见 `Timing_Analyzer_User_Guide.pdf`，下载/在线捕获见 `Fabric_Configuration/Fabric_Inserter/Fabric_Debugger_User_Guide.pdf`。它们的安装版本及hash在资料目录中登记。

## 标准200HP的资源与板级参考

器件参考完整料号为 **PG2L200H-6IFBB676**，PDS器件参数为 `Logos2/PG2L200H/FBB676/-6`；T22仍核对实际丝印、核心板和底板版本。官方资源为159800 LUT6、319600 FF、415个36Kbit DRM、740 APM、10 GPLL/10 PPLL。**FBB676为400用户IO、8 HSST lane**；500IO/16lane是其他封装上限，不作为本板资源。200K等效LUT4不能与实现LUT6用量混算。

专用200HP V1.2手册PDF页14–15给出两颗4Gbit x16、1GiB/x32及R4/R5供电1.5V；实物DDR丝印未核对，容量仍需T23全范围实测。最高1066MT/s×32bit约4.264GB/s只为引脚理论上限，不能承诺持续带宽或token/s。

下面以专用200HP V1.2手册为板级参考；DDR73个信号已与厂商FDC核对，实验FDC通过实现/时序。实际板端与其他外设仍按各卡验收：

| 用途 | 参考引脚／条件 | LM-HW-200HP PDF定位 |
|---|---|---|
| 核心系统时钟 | D18，27MHz；基准周期约37.037ns | 13 |
| DDR参考时钟 | N3/N2，125MHz差分；不能代替实际PLL用户时钟 | 12 |
| 底板备用时钟 | E17，27MHz；核对是否装配和实际使用 | 45 |
| USB-UART | FPGA RX=B24、TX=C24；CP2102/Type-C；当前COM10 | 34 |
| LED0 | A20；高电平点亮 | 41 |
| EEPROM | SCL=A23、SDA=A24；24LC02，I²C参考外设 | 42 |
| SD SPI | SCK=F19、MOSI/CMD=H14、MISO/DAT0=F18、CS_n/DAT3=H15 | 43 |
| SD检测 | SDDEF=G19；有效极性另核，不能直接当数据线 | 43 |
| 实际传感器扩展 | 标准板FMC→MES-FMC-LPC-IO→J2/J3→传感器；实际引脚需三段对照 | 55–59及LM-FMC6–8 |
| 电源/电平 | 底板输入12V、核心供电5V；L6/L7由J20/J24选择3.3/2.5/1.8V | 20–21、55、59 |

UART/SD的GPIO电平按实际bank及供电记录核对；DDR由同版生成约束核对引脚、参考/PHY/用户时钟和复位。不能把所有引脚都指定为LVCMOS33。板载EEPROM可先做I²C通信探针，但不能充当T26真实传感器读数。

## 避免混用与尚缺资料

- **封装写法**：论坛正文有PG2L200H/FBG676，官方料号是FBB676；保留原文，工程按官方与实物核定。官方的pin-compatible说明不免除PCB版本核查。
- **MINI容量矛盾**：LM-HW-MINI页8/10写512MiB，页15写1GiB；LED1/LED2也与标准板对调。已保存 [MINI原件](../sources/logicmatrix/mini-hardware-v1.3.pdf) 作为区别资料，不能据它修改所选标准板合同。
- **50K教程**：[LM-DDR-50K](https://szlogicmatrix.com/forum-post/1089.html) 为PGL50H/PDS2022.1；只作握手讨论参考，不能直接固化200H用户口。
- **其他RISC-V教程**：[环境](https://szlogicmatrix.com/forum-post/1276.html)／[移植](https://szlogicmatrix.com/forum-post/1281.html) 使用MINI/SparrowRV/Windows/SP6.4。不会替换本项目VexRiscv/Coral/运行时，也不是本项目赛事规则。
- **完整板卡包**：[资料获取页](https://szlogicmatrix.com/forum-post/410.html) 正文要求登录。公开PDF已取得，已接收标准200HP资料包并登记hash。包含底板SCH/PCB、核心/底板点位图、原生200H FDC/DDR示例；完整独立核心SCH缺项如上记录；不代用户发帖或联系厂家。
- **实物信息**：Windows主机、CMSIS-DAP适配器与PG2L200H JTAG身份已有本次记录；PCB版本用户报告V1.2、100kHz CRAM路径已有普通逻辑历史通过；封装/速度及DDR/Flash丝印、按键、VADJ跳线和实际传感器仍待T22/T26记录。

## 后续任务如何消费

| 卡 | 资料输入 | 必须留下的新增证据 |
|---|---|---|
| T22 | LM-HW-200HP、原厂200H源/FDC与v7有效FDC、PG-PIN/DDR、LM-PDS/IP/SIM | 实物版本/完整资料包、SP/IP兼容结果、最小工程FDC及route后时序/DRC |
| T23 | T22同版DDR生成物、PG-DDR、LM-LAB-STD第9章 | 用户口地址/握手合同、真实校准、地址高位/全容量与持续带宽 |
| T24 | PG-DS、T22约束、T23DDR、T16/T21 | 分模块LUT6/FF/DRM/APM、时钟/CDC、同固件/向量板端结果 |
| T25 | LM-HW-200HP SD、底板SCH、LM-CONFIG、T18/T19 | 空应用区SD装载、固化配置启动与模型启动区别、完整生成和容量水位 |
| T26 | LM-FMC、LM-HW-STD电平、实际器件手册 | FMC到设备接线、跳线/上拉、真实采样/错误与输出动作 |
| T27 | PG-DDR与T23/T25 | payload/计时窗口、频率、DDR/IP配置、完整请求原始计时 |
| T28 | 原PDS工程/约束与优化卡 | 同输入对照、PnR配置/seed、时序/资源变化与可恢复位流 |
| T29 | LM-CONFIG及T25/T26 | 冷启动两层启动模式、介质/位流身份、长稳/故障现场 |
| T30 | PG-DS、PDS时序与Fabric手册 | 最终实现/约束覆盖、CoreMark分母和频率、探针版与评测版身份 |
| T31 | T30同一板/位流/IP | 同一冻结模型/请求/参考的质量和端到端记录 |
| T32 | catalog、板/工具合同、全部证据 | 干净重建、PDS/SP/IP来源和hash、对应PCB资料与约束 |
| T33 | T32交付清单、LM-CONFIG | 冻结后的位流/固件/SD/模型一致性与可执行恢复步骤 |

任务卡中的产物仍表示待交付项。此次不改变T22–T33状态，不将资料确认计为硬件通过；T00–T21历史工具锁和sim-v1快照保留。
