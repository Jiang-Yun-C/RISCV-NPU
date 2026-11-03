# 项目范围 v1.1（T00）

冻结与审订记录：2026-10-04。主线为 **676＋开源 RV32 主控＋单路完整 Qwen2.5-0.5B 中文语义控制**。根据用户补充线索，已从官网下载 2026 年 FPGA 创新设计赛道紫光同创选题指南与第一轮通知；选题一与本工程 CPU/676/AI 范围吻合。T00 已完成范围交接，实际报名审核和开源复用资格仍为 **UNCONFIRMED**。官方依据及版本差异见 [核对记录](contest-2026-verification.md)。

## 依据与可信度

| 标记 | 含义 | 本次依据与使用边界 |
|---|---|---|
| USER_RELAYED | 用户转述的赛事倾向，未经主办方核对 | [既有依据表](../plan/SOURCES.md) 记载“AI 复杂度倾向按用户说明安排”；没有正式条号、分值或完整原始对话 |
| PROJECT | 项目自行冻结的技术范围或验收目标 | [任务卡](../plan/TASK_INDEX.md)、[交接规范](../plan/HANDOFF.md)、已验收合同；不等同于比赛要求 |
| ASSUMPTION | 待实测或待取得实物资料的假设 | 200HP、1GiB、50/100MHz、16KiB/32B Cache、64 MAC/cycle 均不能写成已确认硬件能力 |
| UPSTREAM | 上游原文，适用范围仅为该组件 | 下列许可证及 CoreMark 运行规则；不能推出赛事允许开源复用 |
| OFFICIAL_CONTEST | 正式赛事指南或主办方原文 | 已取得 2026 紫光同创指南、第一轮通知扫描件和较新的官网通知正文；[来源锁](contest-2026-source-lock.json) 保存版本/hash/页码与 17 项映射。组别存在版本差异，评分权重及复用资格仍未明确 |

下表区分已确认官方要求与项目自行选择；精确章节/页码见 [官方映射](contest-2026-verification.md)。P/N 编号是本工程自编定位标识，不是官方条号。已覆盖所取得选题一的基础/高阶任务、工具、测评和注意事项；官方未给出逐项分值/权重，不自行编造。T32 继续核对补充规则及实际提交细则。

## 比赛相关条目与证据归属

表中的路径由对应任务产出；任务卡链接已存在，未来报告/产物名称不表示已经交付。每项最终证据还须归档到 `evidence/<task-id>/<run-id>/`。

| 编号 | 条目与项目验收口径 | 来源分类 | 实现及验收任务 | 验收证据归属 | 当前覆盖与待确认项 |
|---|---|---|---|---|---|
| R01 | 676 平台；完整器件和板卡版本固定后才作物理结论 | OFFICIAL_CONTEST/PROJECT/ASSUMPTION | [T22](../plan/cards/T22.md)、[T23](../plan/cards/T23.md)、[T24](../plan/cards/T24.md) | 板型/引脚/工具锁、DDR 容量带宽、实现报告和位流身份 | 200HP/1GiB 仅预算；U01/U04/U05/U06 |
| R02 | 官方 RV32I/至少三级流水线、Verilog/SystemVerilog；项目采用开源五级 RV32IM/CSR | OFFICIAL_CONTEST/PROJECT | [T03](../plan/cards/T03.md)、[T09](../plan/cards/T09.md)、[T30](../plan/cards/T30.md) | cpu_gen 配置、固件 ELF/hash、退休/异常签名、最终资源归属 | [T03](../reports/T03.md) 已执行基础配置；不是完整特权符合性或开源复用认证；U02 |
| R03 | 两路 I/D Cache；16KiB、32B line 为初始提案 | OFFICIAL_CONTEST/PROJECT/ASSUMPTION | [T09](../plan/cards/T09.md)、[T13](../plan/cards/T13.md)、[T30](../plan/cards/T30.md) | cpu-feature-matrix.md、冲突/refill/替换波形、缓存维护和资源报告 | T09 验收行为与参数；不能只凭插件名；U01/U02 |
| R04 | 动态分支预测、冒险/冲刷、异常、中断、MRET | OFFICIAL_CONTEST/PROJECT | [T09](../plan/cards/T09.md)、[T21](../plan/cards/T21.md)、[T30](../plan/cards/T30.md) | 定向测试、异常寄存器签名、退休/分支/停顿计数及波形 | T03 只覆盖基础异常/定时器；预测仍待 T09；U01 |
| R05 | FPU 候选单独验收，软浮点为可执行回退 | PROJECT | [T09](../plan/cards/T09.md)、[T12](../plan/cards/T12.md)、[T24](../plan/cards/T24.md) | FPU 指令/CSR/ABI/库测试、数值检查和映射报告 | T03 的 FPU 仅生成/编译；所取得选题一未将 FPU 列为要求；U01 跟踪补充规则 |
| R06 | CPU CoreMark、CoreMark/MHz 与明确分母的 CoreMark/LUT | OFFICIAL_CONTEST/PROJECT/UPSTREAM | [T21](../plan/cards/T21.md)、[T30](../plan/cards/T30.md) | cpu-benchmark.md、源码/编译参数、CRC、原始计时及 LUT 归属 | T21 短测试仅调试；T30 按上游规则正式测量；赛事权重待 U01 |
| R07 | 可解释的流水线、分支、Cache 行为展示 | OFFICIAL_CONTEST/PROJECT | [T09](../plan/cards/T09.md)、[T21](../plan/cards/T21.md)、[T30](../plan/cards/T30.md) | 仿真波形、片上捕获、配置与计数说明 | 探针版本与计分版本分开标识；U01/U05 |
| R08 | 官方 UART/GPIO 等基础外设；项目扩展真实下载、校验和跳转 | OFFICIAL_CONTEST/PROJECT | [T03](../plan/cards/T03.md)、[T17](../plan/cards/T17.md)、[T21](../plan/cards/T21.md)、[T24](../plan/cards/T24.md) | UART 引脚记录、PROTOCOL_BOOT 空目标区、装载/取指同步与执行签名 | 官方基础外设不等于规定 UART 下载；T03 PRELOAD 不替代项目下载验收；U01/U04 |
| R09 | SD 启动、受检模型装载、单份最终模型及失败恢复 | PROJECT | [T18](../plan/cards/T18.md)、[T21](../plan/cards/T21.md)、[T25](../plan/cards/T25.md) | SD 协议日志、模型包 hash、地址边界、断电启动记录 | 禁止目标应用预加载充当下载成功；U04/U06 |
| R10 | 外存访问、CPU/后端所有权、数据一致性和异常处理 | OFFICIAL_CONTEST/PROJECT | [T04](../plan/cards/T04.md)、[T13](../plan/cards/T13.md)、[T14](../plan/cards/T14.md)、[T16](../plan/cards/T16.md)、[T23](../plan/cards/T23.md) | AXI 事务/反压/错误、共享 buffer 可见性、真实 DDR 全容量测试 | T04/T07 行为模型不证明物理 DDR；U06 |
| R11 | 官方支持 YOLO 或轻量大模型 AI 应用；项目选择完整 0.5B 中文程序生成 | OFFICIAL_CONTEST/PROJECT | [T02](../plan/cards/T02.md)、[T11](../plan/cards/T11.md)、[T19](../plan/cards/T19.md)、[T25](../plan/cards/T25.md)、[T31](../plan/cards/T31.md) | 应用模型锁、完整桌面参考、层/token traces、板端连续生成与逐样例输出 | 未找到“模型复杂度优先”评分规则；T02 v2 是适配完整网络，不把算子当整网；U01/U03 |
| R12 | W8 完整功能与冻结质量门槛 | PROJECT | [T05](../plan/cards/T05.md)、[T10](../plan/cards/T10.md)、[T11](../plan/cards/T11.md)、[T15](../plan/cards/T15.md)、[T31](../plan/cards/T31.md) | numeric-v1、operator-manifest、模型包、整数/浮点 checker、独立保留集评分 | T05 已冻结；完整 W8 质量待 T11，板端待 T31；U03 |
| R13 | 单请求中文输入→真实状态→模型程序→CPU 检查→LED/PWM 动作 | OFFICIAL_CONTEST/PROJECT | [T20](../plan/cards/T20.md)、[T26](../plan/cards/T26.md)、[T31](../plan/cards/T31.md) | 固件执行器、接线表、状态成对日志、原始模型输出和可观测动作 | 最小物理演示 UART＋一种传感器＋LED；缺失设备明确拒绝，完整双状态语义在桌面/仿真测试；U04/U07 |
| R14 | TTFT、decode、端到端时延、峰值 DDR 与同源 CPU 对照 | OFFICIAL_CONTEST/PROJECT | [T27](../plan/cards/T27.md)、[T28](../plan/cards/T28.md)、[T31](../plan/cards/T31.md) | performance-baseline.md、optimization-decision.json、逐请求时间戳与 final-evaluation.md | 最低交互目标待 T27 实测冻结；≥5 token/s 仅冲刺方向；U07 |
| R15 | 稳定性、超时、非法请求、传感器失联及故障恢复 | PROJECT | [T20](../plan/cards/T20.md)、[T26](../plan/cards/T26.md)、[T29](../plan/cards/T29.md)、[T31](../plan/cards/T31.md) | 故障注入、恢复日志、会话隔离、数值/装载回归 | 无效模型输出不执行；未排空总线不能宣布空闲；U04/U07 |
| R16 | 可重建工程、来源/贡献说明、许可证与最终演示提交包 | OFFICIAL_CONTEST/PROJECT | [T32](../plan/cards/T32.md)、[T33](../plan/cards/T33.md) | docs/delivery、干净目录重建、贡献矩阵、发布清单、最终 hash | 正式清单及复用资格仍未确认；U01/U02/U03/U05/U08 |

## 主线、增强与最低交付

主控优先采用 [第三方锁](../../third_party/lock.json) 的 VexRiscv。当前 CPU 基础执行已由 T03 验收，Cache/预测及 FPU 执行按 T09 处理。模型沿用 [T02 v2 模型锁](application-v2-model-lock.json) 的应用 LoRA 合并 FP32 权重、原始 tokenizer 和 [应用协议 v2](application-v2-contract.md)，不退回未适配的失败基线。网络保持完整 0.5B；单路请求、中文指令、温度/光照状态、LED/PWM 风扇设备语义固定。

W8 基线严格沿用 [数值 v1](numeric-v1.md) 和 [T05 阈值](../../configs/t05-thresholds.json)：W8A8/group64、INT32 点积、FP32 恢复与 KV；合法成功≥90%、拒绝≥95%、相对同 split 浮点下降各≤3 个百分点，成对状态与 EOS 100%。这些是项目门槛，非赛事阈值。50 条开发集与 200 条保留集分开；已看过并据此改动模型/提示的保留集不能继续充当独立验收集。

Coral 的 [T07 结论](../reports/backend-sim-feasibility.md) 为 SUPPORT_WITH_LIMITS。T08 才选择一个 SIM_SELECTED 后端并定义 API、能力、错误语义、地址图和计数；T00 不提前选中 Coral 或替 T08 定义底层描述符。FPGA_QUALIFIED 仍需 T22–T24。只有 T07 否决或 T24 证实无法映射才启动 F01，不同时开发多个后端；开源核不被赛事认可时另作路线决策，不自动追加自研 CPU。

| 范围层次 | 固定内容 | 完成依据 |
|---|---|---|
| 必做：前期独立交付 | T00–T21 的模型参考、CPU 功能、真实 RTL 算子/驱动、UART/SD 协议、选定层及虚拟应用；仅桌面软件/VCS | T21 的 sim-v1 验收与可回归快照；不要求 PDS、厂商 DDR IP 或实物 |
| 必做：最终板端交付 | 完整 W8 0.5B 板端分词/连续生成、真实 CPU 驱动、真实状态改变动作、稳定性、正式 CPU/应用评测、可重建提交材料 | T22–T33 各自验收；T25 整网、T26 应用、T30/T31 正式评测、T32/T33 资格与发布 |
| 性能优化：按测量选择 | T27 至多选择两类主要优化；O01 W4、O02 注意力/向量、O03 Prefill/搬运重叠 | 仅被选中的 O 卡加入 T28 及最终回归，未选中保持 DEFERRED；保留 W8 回退 |
| 展示增强：可选 | O04 板端显示；额外界面不能成为最小闭环的前置条件 | 核心闭环通过后按需启用，选入发布同样验收 |
| 不在本轮 | 语音、摄像头、Linux、7B、多请求、MoE、投机解码、Ising 第二加速器、默认自研 CPU/多后端并行建设 | 需另有范围变更决策才进入计划 |

最终最低交付必须具备完整模型、CPU 数据一致性、真实启动及真实应用闭环。外设可简化为 T26 明定的单传感器/LED 演示，但不得把桌面模拟数据写作实物采样，也不得静默改写 T02/T31 的评分分母。受限程序执行器执行条件与动作，模型负责语言到程序的转换；不能以规则解析器替代模型后归功于模型。

## 前期冻结的计时口径

计时协议标识为 `scope-timing-v1`。T27 依据实际计数器精度冻结测量配置和最低可接受响应时间、内存余量；目前不设置板端秒数或 token/s 验收门槛。后续若改动边界，须升版本并重测对照组。

| 指标 | 起止点与分母 |
|---|---|
| 冷启动加载 | 从复位释放到固件、tokenizer、完整模型校验完成并允许接收请求；单列介质读取、校验和搬运，另报热启动；不计入稳态 decode |
| 请求接收 t0 | 完整合法长度的请求帧最后一字节到达板端接收接口；由同一时间基准记录。输入传输耗时另报；排队、状态采样、解析和分词均在 t0 之后计入端到端时间 |
| 分词 | 模板/输入开始编码至输入 token 就绪；同时保存输入文本、模板 hash 与实际 token 数 |
| Prefill | 输入 token 就绪后，第一次模型计算开始至首个输出 token 被选定；包含输出投影/采样，并明确此边界 |
| 模型 TTFT | `t_first_selected - t0`；包含接收后的状态采集、分词、调度和首步模型时间 |
| 可见 TTFT | 首个非特殊 token 对应的可输出文本字节发送完成时间减 t0；UTF-8 可能等待多个 token，因此独立于模型 TTFT；无文本输出记 N/A |
| Decode | 输出 token 选定时刻 `t1…tN`，`(N-1)/(tN-t1)`，单位 token/s，排除首 token；N 包含实际生成的 EOS 等特殊 token，同时另报非特殊 token 数。N≤1 或无有效时间跨度记 N/A |
| 意图检查与动作 | 完整输出/EOS 后，程序验证、状态条件执行、实际输出写入与确认各记区间；无效输出记拒绝及原因 |
| 请求总时延 | 最终响应最后一字节发送完成且动作已确认时刻取两者较晚值，减 t0；非法请求截止于完整拒绝响应。物理稳定时间若另测，明确传感器/观测点 |
| 超时与聚合 | 记录超时上限、失败阶段和已生成 token；性能成功样本的 N、中位数、P95 与全部请求中的失败/超时数同时公开；不可丢弃慢请求后冒充总体 |

原始区间允许重叠，汇总按时间轴并集解释墙钟总时延，不把搬运与计算重叠时间重复相加。仿真周期与板端计时分表，不能用假设频率把 VCS 周期冒充板端速度。

每个对照固定模型 revision/适配器/包 hash、量化、tokenizer/模板、输入与输出 token、上下文、greedy/采样、终止条件、seed、CPU/后端频率、内存、Cache、后端与回退项、启动模式和计时协议。CPU 软件与加速使用同一完整量化模型；若需缩短请求，双方同改并另列配置。不同输出长度的自由生成不得当作等工作量加速比；超时只报告可证明的界限。

正式 CoreMark 采用上游允许的移植方式，至少运行 10 秒，规定 seed/2000-byte 工作集验证通过，统一编译参数，保留原始日志；T21 短测试不可报告为正式成绩。CoreMark/MHz 写明频率和存储配置，CoreMark/LUT 同时写 CPU LUT 与系统 LUT 的归属/计算口径，最终赛事认可的分母待 U01。上游依据：[EEMBC Run Rules](https://github.com/eembc/coremark#run-rules)（2026-10-04 核对；这是基准规则，不是赛事原文）。

## 开源、生成 RTL 与第三方 IP

这里只登记已读来源和交付要求；组件许可证与赛事允许范围分别核对。来源链固定为“上游 revision → 生成配置/工具版本 → 生成 RTL hash → 本地改动 → 仿真/实现证据”。T32 的贡献矩阵分别列原有、配置、移植、优化、新增，不把开源 CPU、上游 RVV 或工具生成 RTL 记作全部原创。

| 对象 | 已有身份/原文 | 项目使用与交付要求 | 仍待关闭 |
|---|---|---|---|
| VexRiscv | baf7dc82f855eddaf5b0a20a6802c526f127e38a；锁定 checkout 的 LICENSE 为 MIT | 保留版权/许可证；固定 SpinalHDL、生成源码、参数、输出 RTL 和本地改动；本次许可证副本/hash 随证据归档 | U02：开源主控及生成 RTL 的赛事认可、原创贡献口径；工具依赖清单由 T32 补全 |
| Coral | 382b5c12030ad8eb74ab8deafb2529301faeab16；[本地 LICENSE](../../third_party/coralnpu/LICENSE) 为 Apache-2.0 | 保留许可证与适用 notices、标注修改，按 T06 锁定生成/编译来源；T08 决定是否采用 | U02/U08：加速器复用评分和最终包含的子依赖；当前 RVV 执行不能表述为已验证矩阵引擎 |
| Qwen 及应用适配 | base 7ae557604adf67be50417f59c2c2f167def9a775；[上游 LICENSE](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct/blob/7ae557604adf67be50417f59c2c2f167def9a775/LICENSE) 为 Apache-2.0；适配器/合并权重由应用锁标识 | 保留许可证与适用 notices，标识训练/合并改动；不能写成原版官方权重；训练来源和导出步骤可追溯 | U03/U08：预训练/微调模型的比赛认可、提交形式与最终材料清单 |
| SpinalHDL/Chisel、编译器与 CoreMark | 已有工具锁及 T03/T06 生成配置；CoreMark 最终版本由 T21/T30 锁定 | 保存版本、输入/生成物与许可证来源；每个实际分发组件独立登记，不将一个顶层许可证扩展到整套依赖 | U08：完整依赖和可重建来源清单 |
| PDS、DDR/PLL/RAM IP、下载器和板级调试 IP | 尚无本项目匹配器件/IP 的资格结论 | T22 取得版本/许可与工程重建条件，T23/T24 实测；专有工具/IP 的交付形式依原文确定，不默认打包安装文件 | U04/U05/U08；不成为 T00–T21 前置 |

VexRiscv/Coral 的固定 revision 网页此次未能通过浏览工具取回，许可证以现有锁定 checkout 原文为依据并保存 hash，不把网页抓取失败写作已在线验证。[VexRiscv 固定来源](https://github.com/SpinalHDL/VexRiscv/tree/baf7dc82f855eddaf5b0a20a6802c526f127e38a) 与 [Coral 固定来源](https://github.com/google-coral/coralnpu/tree/382b5c12030ad8eb74ab8deafb2529301faeab16) 用于定位。

## 未决项与阻塞范围

U01/U03/U04 已有部分官方依据，其余缺口仍开放；U02/U05–U08 也未关闭。责任人只标角色，不安排周次、工期或人员承诺。官方通知中的日期仅作为外部事实存于 [核对记录](contest-2026-verification.md)，不转为项目排期。关闭时须保存原文/实测、来源版本/hash、结论和受影响任务，并追加决策记录。

| 编号 | 待确认内容 | 责任角色 | 受影响任务 | 阻塞结论及关闭证据 | 当前可继续 |
|---|---|---|---|---|---|
| U01 | PARTIAL：2026 赛事/赛道/选题一与官方日期已取得；实际报名/组别、通知组别差异、评分权重及补充细则待核 | 共同：赛事联络 | T00、T09、T21、T30、T31、T32、T33 | 官方条款已映射，但实际参赛资格不可确认；需报名审核记录与未明确细则，不能把旧年度提交模板当本届要求 | 按已确认条款继续实现；不因报名状态未知停止通用技术研究 |
| U02 | 开源主控/加速器、SpinalHDL/Chisel 生成 RTL、原创贡献与第三方核是否认可 | 共同：赛事联络/硬件 | T00、T03、T06、T08、T09、T24、T32、T33 | 复用路线的参赛资格不可确认；须正式规则或可追溯答复。若被否决，重开范围/路线决策 | 仿真研究和 T08 技术选型；不自动追加自研 CPU |
| U03 | PARTIAL：官方支持轻量大模型应用；预训练/LoRA/执行器组合及具体贡献认可仍待核 | 共同：赛事联络/软件 | T00、T02、T10、T11、T20、T25、T31、T32、T33 | 方向匹配不等于当前实现已获认可；模型来源/适配与贡献仍需说明 | 使用已冻结 T02 v2 模型/协议继续软件与 RTL 验证 |
| U04 | PARTIAL：2026-10-09用户已选标准MES2L676-200HP（200Pro+）；实际料号/PCB版本/引脚/电气/介质/连接待核 | 硬件：平台 | T22、T23、T24、T25、T26、T30、T33 | [板卡合同](../../board/mes2l676-200hp/board-contract.json)登记选择及官方FBB676；公开共享板资料不证明实物版本，仍须匹配原理图。选题一平台条件保持原官方口径 | 参数化仿真与资料准备；1GiB仍须T23实测 |
| U05 | PARTIAL：PDS2022.2-rc3 shell/ADS已通过；200H匹配SP/IP、PLL/RAM及调试/下载流程待验 | 硬件：工具与平台 | T22、T23、T24、T30、T32、T33 | [HMIC_S官方资料](pds-board-references.md)要求PG2L200H的PDS至少2022.2-SP1.2；当前rc3不替代该资格。T22核实IP包/许可和最小实现，T23/T24验收实板 | T00–T21桌面/VCS；现有工具检查与200HP资料准备 |
| U06 | 实际 DDR 容量、地址范围、可用持续带宽及整网峰值分配 | 硬件：存储/软件：运行时 | T10、T12、T23、T24、T25、T27 | 1GiB 可装下并稳定运行的板端结论不可确认；须全容量/带宽及真实包和峰值分配实测 | T10/T12 先做逻辑预算与可溢出检查，T23 再核实 |
| U07 | 最低板端交互目标、超时上限、内存余量及优化选择 | 共同：性能与应用 | T27、T28、T29、T31 | 最终响应目标达标不可确认；须 T27 用 scope-timing-v1 实测并冻结条件/目标 | 先实现完整功能与原始计数；≥5 token/s 不作前置门槛 |
| U08 | 最终提交清单、工具/IP/模型的分发形式、全依赖许可与贡献矩阵 | 共同：交付 | T21、T30、T32、T33 | 最终包可提交/可分发结论不可确认；须正式清单、逐组件来源/许可和干净重建记录 | 保存来源、生成配置和历史成功/失败证据；不代发赛事咨询 |

## 交接与变更

T02 的应用范围现由本合同接收其已验收 v2；保留原版失败记录和历史决定。T08 接收本范围及 U02/U03 风险，在 T07 已完成的基础上进入 READY；不是已经作出 SIM_SELECTED 决策。T09 接收 R02–R07，T22 接收 U04–U06 并继续后置，T27 接收计时协议，T32 接收全 R/U 映射，正式提交前关闭相关外部未决项。

变更记录须包含 version、reason、producer、consumers、affected_tests。比赛资料到齐、禁止复用、板型/容量变化、模型/数值变更或后端否决时，重新审查受影响任务和证据；不能把 T00 DONE 当作正式资格豁免。机器可读边界见 [T00 配置](../../configs/t00-scope.json)，复核入口 `make t00`，结果见 [验收报告](../reports/T00.md)。
