# 技术决策记录

## D-PDS-200HP-20261009：标准200Pro+资料与版本资格

- 用户明确选择标准MES2L676-200HP（200Pro+）；建立 [板卡合同](../../board/mes2l676-200hp/board-contract.json)，实际PCB/连接及DDR容量由T22/T23核实。
- 逻辑矩阵公开资料和紫光官方器件/封装/IP原件已保存URL/hash，[交接表](pds-board-references.md)提供PDF定位、参考引脚和T22–T33输入；MINI与50K例程不作为本板合同。
- 当前PDS2022.2-rc3 shell/ADS再次PASS，并采集实际命令帮助；PG2L200H HMIC_S官方要求PDS2022.2-SP1.2+，本机IP清单/实际index也有差异。T22先核验受支持SP/IP，确认后更新独立工具合同，不默认重新安装或直接套用100H探针。
- 新建 [pango-pds skill](/home/Jiang/.codex/skills/pango-pds/SKILL.md)，T22–T33补充资料、操作和验收。仅更新文档及工具证据，任务状态/依赖与历史sim-v1保持原记录。

本文件登记范围与实测产生的技术决策。T00 已冻结范围并登记外部未决项；2026 官方指南/通知已取得，开源复用、实际参赛资格和板型仍待确认，见 [范围 v1.1](project-scope.md)。各条中的当时状态作为历史保留，当前状态以任务登记表为准。

## D-T02-001：固定浮点模型与桌面应用范围

- 来源：T00/T02/T20 现有任务卡及本次用户“完成 t02”的执行请求。
- 模型固定为 Qwen2.5-0.5B-Instruct，revision `7ae557604adf67be50417f59c2c2f167def9a775`；官方 BF16 文件完整加载后以 FP32 运行，不微调、不量化。
- 应用输入为中文指令和温度/光照快照，设备为 LED/PWM 风扇；快照为桌面测试输入，不代称物理传感器采集。
- 50/200 条数据在推理前固定，保留集不能用于调参；项目目标为合法 ≥90%、正确拒绝 ≥95%。
- 影响：T05/T07 可取得实际模型身份和形状，T20/T26 接收语义草案；不变更 T00 的正式规则待确认状态。

## D-T02-002：保留完整失败结果，暂不关闭质量关口

- 依据：[基线报告](../reports/model-fp-baseline.md)；正式评测结束于 2026-10-03 02:48:38 UTC（America/New_York 为 2026-10-02）。
- 四轮开发提示尝试均未达标。冻结的 v3 保留集合法成功 62/160、拒绝 20/40、状态成对通过 0/20。
- 决策：T02 登记 BLOCKED，交付物/执行完成与验收通过分开；T05 不自动解锁。既不降低阈值，也不改写 FAIL 证据。
- 下一关口：T08 前另立有记录的任务收窄或模型/语义方案变更，并以新独立协议验收。当前保留集不能据失败结果反复调参。
- 边界：本次未替换模型、未收窄原测试集、未连接或驱动真实设备，未据桌面 GPU 测量宣称板端速度。

## D-T02-003：以应用适配和受限程序执行解除质量阻塞

- 来源：用户要求“为什么 blocked 解决这个问题”；在保留原失败证据的前提下修复。
- 完整官方 0.5B base 采用 LoRA 应用训练，合并为相同 494,032,768 参数结构的 FP32 权重；模型负责中文程序编译，桌面确定性执行器负责条件、查询、动作和整条拒绝。网络/精度不缩减，不用规则解析中文或硬编码测试答案。
- 新 2048/50/200 数据先固定，再训练；只用 train 更新、dev 选择，发布冻结后首次运行新 heldout。合法 ≥90%、拒绝 ≥95% 不变，传感器成对要求提高为全部通过。
- 实测合法 156/160、拒绝 40/40、成对 20/20；离线重载、token、冻结和证据审计均通过，见 [v2 报告](../reports/model-fp-baseline-v2.md)。T02 DONE，T05 READY。
- 下游 T05/T07/T10 必须使用新应用模型锁，T20 接收程序协议并实现固件；T26 仍负责物理传感器。T00 赛事/复用资格/板型待确认状态不变。
- D-T02-001 的“不微调”与 D-T02-002 的 BLOCKED 作为 v1 历史决策保留；当前模型/协议以上述 v2 为准，不回写旧保留数据或 FAIL 证据。

## D-T05-001：冻结 W8 数值、规约顺序与质量门槛

- 来源：用户“执行 t05”；固定输入沿用 T02 v2 的合并 FP32 模型与原始 tokenizer。
- [数值 v1](numeric-v1.md) 固定 W8A8、输入 K 维 group=64、对称 [-127,127]、ties-to-even、INT32 组内点积、FP32 逐组恢复和跨组求和、FP32 bias/norm/KV、共享 embedding/head。原始 tokenizer 的 EOS=151645，不回填模型默认采样。
- 累计敏感性检查发现 FP32 规约末位差异可跨越动态 A8 舍入边界；固定相邻配对二叉树、sqrt/reciprocal 和稳定 sigmoid。独立实现通过原有误差门槛，未因失败放宽阈值；所有 FAIL 证据保留。
- [验收报告](../reports/T05.md)：24 个真实尺寸案例、30,680,832 个整数点积逐位一致、149 个文件全量复生一致。仅层 0 累计与 KV 已验收，不代替完整 24 层量化质量、后端或板级验证。
- T11 使用 [已冻结阈值](../../configs/t05-thresholds.json)：合法≥90%、拒绝≥95%、相对同 split 浮点下降分别≤3 个百分点；成对状态/EOS 均为 100%。保留集不参与量化调参或选择。
- T05 DONE；T07 仍需 T06，T10 仍需 T08。T10/T12 用实际包和峰值分配验证容量，当前脚本结果只表示逻辑容量与明确调度的访存/MAC 公式。

## D-T06-001：真实 RVV VCS 执行通过，继续外存评估

- 固定 Coral commit `382b5c12030ad8eb74ab8deafb2529301faeab16`、Bazel 9.1.0、上游 GCC 16.1.0，选定 `RvvCoreMiniAxi`；源代码无补丁。
- 六组执行、四个负例及 56 项回归通过，见 [报告](../reports/coral-build.md)。标量对照不能替代 RVV；本次已实际执行 RVV 加宽加法、乘法和规约。
- VME/Zvt 源码存在，但本 target 未启用/执行；不以 RVV 运算证明矩阵引擎性能。
- T06 DONE，T07 READY；T07 验证 128-bit/ID6 外存接口与 T04 的适配，再测超 TCM Qwen 工作集，T08 决定后端。无 PDS/板级结论。

## D-T00-001：冻结主线与分阶段执行边界

- 来源：用户“完成t00”、[T00 卡](../plan/cards/T00.md) 与既有任务卡/验收证据；记录日期 2026-10-04，不代表排期。
- version：scope-v1；reason：为后续接口选择提供完整范围与证据归属；producer：T00；consumers：T02/T08/T09/T22/T27/T32；affected_tests：范围映射、登记表/链接/冻结身份审计，后续范围变化重验受影响卡。
- 主线固定为 676＋开源 RV32 主控＋单路完整 Qwen2.5-0.5B 中文语义控制；接收 T02 v2 适配模型、应用协议与 T05 W8 数值，不退回原版失败方案。
- T00–T21 仅桌面软件/VCS，不依赖 PDS、厂商 DDR IP、资源时序报告或实物；PDS/实物从 T22 起后置。200HP/1GiB 仅设计假设；不安排周次、工期或截止日期。
- T07 的 SUPPORT_WITH_LIMITS 可供 T08 决策；只有 T08 能标 SIM_SELECTED，只有后续平台验收能标 FPGA_QUALIFIED。未触发 F01/O01–O04，不自动追加自研 CPU。

## D-T00-002：范围完成与正式资格分开登记

- version：scope-v1；reason：正式赛事文件尚未取得但卡片允许技术研究继续；producer：T00；consumers：T08/T22/T30/T31/T32/T33；affected_tests：16 个 R 条目映射、8 个 U 未决项、来源分类和提交资格标记。
- [范围 v1](project-scope.md) 区分 USER_RELAYED、PROJECT、ASSUMPTION、UPSTREAM 与 OFFICIAL_CONTEST；目前没有 OFFICIAL_CONTEST 条款。所有官方条号/分值待确认，不宣称未知评分表已完整覆盖。
- U01–U08 登记责任角色、阻塞结论、受影响任务及关闭证据；正式资格/开源复用保持 UNCONFIRMED，T32/T33 不能凭 T00 DONE 宣称已获认可。
- 上游许可证按锁定源文件保存；生成 RTL 记录配置/工具/输出 hash，贡献矩阵区分复用、配置、移植、优化、新增。赛事不认可复用时重新评估路线，不自动转为自研 CPU；本次不代发消息。
- T00 依据其“范围与未决项登记”验收关闭；T08 普通依赖满足，进入 READY。T22 及后置任务仍受外部条件约束。

## D-T00-003：冻结计时边界和最低交付层次

- version：scope-timing-v1；reason：避免把仿真周期、单算子或不同输出长度混作整网性能；producer：T00；consumers：T08/T21/T27/T28/T30/T31；affected_tests：计数/时间戳、同源对照、冷启动与请求区间、失败/超时统计。
- 定义完整帧接收 t0、模型/可见 TTFT、含 EOS 的 decode token 分母、最终响应与动作完成的端到端边界；完整协议见 [范围 v1](project-scope.md)。重叠区间不重复累计。
- T21 是可独立交付的仿真基线；最终交付仍要求 T25 完整模型、T26 真实闭环及 T30–T33 评测/材料。单传感器/LED 可作最低实物演示，不能静默改变完整语义或评分分母。
- 最低板端交互目标由 T27 基于实测冻结，≥5 token/s 仅冲刺方向；T05 质量门槛继续有效。性能优化按瓶颈选择，展示增强 O04 可选；选入发布的 O 卡必须纳入 T28 与最终回归。

## D-T00-004：取得 2026 官方指南并修正依据分类

- 来源：用户补充“fpga嵌入式大赛你可以搜一下”；[官方资料核对](contest-2026-verification.md) 与 [原件来源锁](contest-2026-source-lock.json)，记录日期 2026-10-04。
- version：scope-v1.1；reason：官方资料已可取得，不能继续把所有比赛要求写成推测；producer：T00；consumers：T08/T09/T22/T30/T31/T32/T33；affected_tests：17 项官方定位映射、来源 hash、范围分类和交接一致性检查。
- 匹配 2026 FPGA 创新设计赛道紫光同创选题一；已确认 RV32I/至少三级、两路 Cache、动态预测/异常中断、轻量模型应用及性能/ILA 要求。五级 RV32IM、FPU、SD、具体 Cache 容量和 Qwen 实现保持项目选择，不扩大为官方要求；未找到模型复杂度优先的评分依据。
- 保存第一轮通知 PDF 和更新的官网正文；组别两组/三组存在差异，实际报名及适用组别仍待核。官方日期作为外部事实记录，不转为项目排期。
- 现成核复用、生成 RTL、模型适配及最终分发材料仍没有明确资格结论。U01/U03/U04 部分核实，U02 等保留。T09 对照官方完整异常/中断措辞列明覆盖缺口，T32/T33 接收能力考核与发布交接项。
- 本次只修订范围依据，不选择后端，不改变模型/数值，不开启自研 CPU，不联系主办方。原 T00 v1 证据和当时“未取得”判断作为历史保留，当前事实以本决策为准。


## D-T08-001：SIM_SELECTED，冻结单一 Coral RVV 仿真路线

- 来源：用户“完成t08”、T00 范围 v1.1 与 T07 SUPPORT_WITH_LIMITS；记录日期 2026-10-04。
- version：system-v1/backend-api-v1/memory-map-v1；reason：向导出器、C runtime、驱动与内核移交同一接口；producer：T08；consumers：T09/T10/T11/T12/T13/T14/T15/T17/T18/T19/T24/T27；affected_tests：合同/头文件/地址边界、数值向量、包读取、CPU-后端所有权及相关 RTL 回归。
- 选择 **SIM_SELECTED：Coral RvvCoreMiniAxi**，commit `382b5c12030ad8eb74ab8deafb2529301faeab16`，VME=false。T07 已证明外存与代表线性正确；性能低效和软件覆盖成本已接受为功能优先仿真路线限制，不宣称满足板端 token/s。
- 线性投影使用 Coral RVV；FP32 attention/vector、入口动态量化、tokenizer 和应用控制使用主控 C，并逐项计时。能力表区分 T07 探针实测和 T11–T16 待实现能力；不把形状相同当作所有层已经验证。
- [系统合同](system-contract-v1.md)、[API 合同](backend-contract-v1.md)、[地址图](memory-map-v1.json) 和 [能力表](backend-capabilities-v1.json) 冻结同步单在途、错误恢复、地址域转换及回退计数。复用原生 TCM/CSR，不建设第二套 64B 描述符硬件。
- T10 冻结物理模型包及 layout_id；本卡只给出逻辑 view，未知布局拒绝。T03/T07 历史地址保持原证据，系统集成须迁移到新图；T10/T12 继续验证实际包和峰值容量。
- F01/O01–O04 未激活。FPGA_QUALIFIED 留给 T22–T24；正式资格和复用限制仍 UNCONFIRMED。T08 的选择不会消除这些外部未决项。

## 2026-10-05：T09 CPU 候选与公共验证入口

- T09 DONE：两路 16KiB/32B I/D Cache、DYNAMIC 预测、默认 ILP32 软件浮点；ILP32F 为已执行定向测试的独立候选。配置/端口/CSR 缺口见 [功能矩阵](cpu-feature-matrix.md)。
- 生成时对隔离导出的锁定 VexRiscv 应用 BHT reset、I refill error clear、按 refill 轮换 victim 三个局部修正。禁止改写上游用户 checkout；保留未修复开发失败记录。
- 已验收 VCS + cocotb 2.1.0、独立签名/协议/波形比对、多 seed 复现和框架负例。store access fault 传播、部分 CSR/mtval 符合性仍属 U01 缺口。
- T13/T17 READY；后续共享所有权、真正协议启动、RAM/PDS/板级门槛保持独立。

## D-T10-001：固定 W8 模型包与生产端验证

- 来源：用户“完成t10”；记录日期 2026-10-05。version=`model-pack-v1`，producer=T10，
  consumers=T11/T12/T14/T15/T18/T19；affected_tests：导出/独立读取、全部参数、坏包与数值 fixtures、运行时预算。
- 使用 T05 冻结的适配权重和原始 tokenizer，不改变量化/生成语义。物理 `layout_id=0x1001`，
  按输出行和 K64 组顺序直接流式读取，embedding/head 的 W8/scale 各只存一次；T08 逻辑 view 仍为 1。
- 290 个源张量全量逐位检查，536,731,456-byte 完整包两次重建一致。3 个合法/21 个非法 fixture
  独立验证，保留坏包的原始 FAIL/非零退出；111 项项目回归通过，见 [验收报告](../reports/T10.md)。
- 具体 KV/激活/reduction/logits/程序/堆栈/BPE/传输分配受 T08 分区约束。实际 weights＋其余分区
  完整预留为 927,776,384 bytes，假定 1GiB 额外保留 145,965,440 bytes；T12 的实现峰值与 T23 板容仍待验收。
- T10 DONE，T11 READY。producer 通过不冒充 T14/T15/T18 RTL 消费通过；K65 小包只验证格式尾组，
  现有后端应返回不支持。T11 整网 W8 质量、FPGA/PDS/实板资格边界不变。

## T11：完整 C W8 参考与质量冻结（2026-10-05）

- T10 模型包及 T05 阈值保持原身份；C 完成 24 层前向与 greedy 控制。
- 超越函数使用 double libm 后立即舍入 FP32，消除末位近似跨越动态量化边界的累计偏差；未修改量化策略或放宽容差。
- context=1/4/8/512 各 8 步固定 token 的完整 KV/logits 独立比较通过；小型 fixtures 与受管理完整 traces 发布给 T15/T19。
- 开发通过后冻结，再评测保留集；同 split 浮点对照、全部 T05 质量门槛和独立进程复跑通过。详见 [验收报告](../reports/T11.md)。
- T11 DONE，T12 READY；T12 接收同一 C 实现与原始 tokenizer，RTL/FPGA/实板边界不变。

## 2026-10-05：T14 真实 Coral 分块传输交接

- version：streaming-t14-v1 私有 ABI（0x53543134），保持 system-v1/backend-api-v1/model-pack-v1/numeric-v1。producer=T14；consumers=T15/T16/T27。
- reason：真实 RVV 微程序直接从外存读取主权重，64B scratch、128 行分块；输出 pitch 按 FP32 的 4B 对齐，以支持合法全局行跨度。未加入外置 DMA。
- affected_tests：9 组实际 VCS/cocotb、1,788,141 独立检查、4 个隔离负例、164 项回归和归档/交接复核。
- T14 DONE，T15 READY；公开 numerical mask 保持零，完整算子/词表由 T15、主控闭环由 T16 验收。

## 2026-10-05：T15 完整 W8 线性组件交接

- version：linear-t15-v1 私有 ABI（0x4c4e3135）；数值、API 和 T10 包保持原身份。producer=T15；consumers=T16/T19。
- 全部组由 Coral RVV dot 和 Coral 标量 FP32 恢复/规约/bias 执行；生产路径只返回最终输出，审计成本计入总量。
- 全词表 M1 的 151936 行通过不重叠分区覆盖，保存并校验全部实际 logits；分区周期和不得作为单次连续提交延迟。
- affected_tests：590 组真实 VCS/cocotb、437,724,080 项检查、7 个隔离负例和 168 项回归。详见 [报告](../reports/T15.md)。
- T15 DONE，T16 READY；默认未绑定 context mask 仍为零。真实 VexRiscv 控制、平台 transport 和单次完整 head 事务由 T16 复验。
