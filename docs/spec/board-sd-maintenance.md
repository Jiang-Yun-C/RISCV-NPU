# 板载 SD 读写维护

本项目支持把独立 SRAM CPU/UART/SPI 工具临时下载到 FPGA，经 CP2102/COM10 维护板上 SD。
SD 卡可以留在板卡槽内。执行入口和已通过的工具登记在
`configs/board-sd-maintenance.json`；每次任务的当前状态在 `configs/opt17-v3-live-status.json`。

公共入口均不打开硬件：

| 命令 | 用途 |
|---|---|
| `make board-sd` | 当前记录、串口锁、文档和版本化执行器入口 |
| `make board-sd-plan ARGS='…'` | 从两个实际镜像派生布局，生成新plan和精确writer_config.h |
| `make board-sd-tool ARGS='--plan JOB/plan.json'` | 验证配置/产物/生产者绑定，查找可原样复用的已归档工具 |
| `make board-sd-native-test ARGS='--plan JOB/plan.json --run-id NEW_ID'` | 实际C程序执行完整源/目标镜像，含边界与错误拒绝 |
| `make board-sd-verify ARGS='--receipt RECEIPT'` | 独立解码UART CRC、每条命令、每个应用扇区、完整物理摘要和邻扇区 |
| `make board-sd-watch ARGS='--receipt RECEIPT'` | 查看既有进程阶段/原始日志与实测速率估算，不启动新任务 |
| `make board-sd-test` | 小镜像/实际C搬移/损坏数据/CRC/布局/边界回归，无硬件动作 |

例如，离线重建本次已接受的 A→v3 计划：

```bash
make board-sd-plan ARGS='--current-image evidence/OPT01/opt01-integration-20261018-v2/recovery/sd-full-model.img --target-image variants/opt10_r1_v3_opt17_offline_20261024/artifacts/candidate-sd.img --card-receipt evidence/OPT17_V3_BOARD_SD/v3-opt17-board-SD-20261024-v4-continuation/manifest.json --out NEW_JOB_DIRECTORY'
make board-sd-tool ARGS='--plan NEW_JOB_DIRECTORY/plan.json'
```

这是历史事务的离线复现；不能据此认定当前卡仍为旧A。当前卡内容由新鲜完整物理摘要证明。
`plan`会验证NXSDV1头CRC、保留区、全部应用/模型字节及padding；模型必须完全相同。
布局和移位量从镜像头计算，不固定为1扇区或58扇区。该入口支持扩大/等范围更新；
缩小及回退另按已保存扩展区建立恢复合同。目标模型改变时另建完整写入流程。

物理执行器位于登记表 `recipes` 指向的版本化目录。当前已实测的执行器为
`variants/opt10_r1_v3_opt17_boardrun_20261024/`，现有任务应读其HANDOFF和活动收据接续。
不要再次启动其已完成的写卡事务。新任务新建执行身份，更新数据合同并核验本次收据；
CLI不把新候选自动映射到旧脚本的固定哈希。

换布局时先生成plan/config并检查工具缓存。完全相同配置可复用已固定的SBIT/SVF；
新配置使用 `scripts/prepare_sd_writer.py --run-id NEW_ID --config JOB/writer_config.h`，
并保存新的维护工具身份、完整镜像主机验证、十表/资源、原生SVF逐字节及ID/CRC/DONE检查。
这属于独立维护工具，不修改主应用候选的RTL、ROM或已闭合实现。
协议/RTL源码变化时重新验证实际CPU/UART/SPI小例；原始收据留在原目录。

现场顺序如下，沿用会话中已明确的执行范围，不反复确认常规可逆步骤：

1. 核对唯一JTAG、CP2102身份、全局串口锁及实际进程。临时CRAM工具不访问DDR或Flash。
2. COM10原始采集先就绪，再下载工具，核对原生ID/CRC/DONE。
3. 实读SD CID/CSD/OCR/容量、旧头、全部扩展扇区和覆盖范围外的下一sector。
4. 在卡上完整CMD17读取旧镜像并算SHA256。摘要与冻结源镜像相同后，使用该源镜像加上
   实际读取的全部扩展扇区构成完整覆盖区前像；保存独立邻扇区及来源收据。
5. 仅在CID、完整旧摘要和已保存前像均匹配后ARM。向高LBA搬移必须由尾到头；
   每次CMD24等待busy释放并立即CMD17读回逐字节比较。随后写应用，最后提交精确镜像头。
6. 再对全部新镜像实际CMD17/SHA256，核对邻扇区未变并DISARM；独立解析原始回应CRC和全部写范围。
7. 通过后才配置主应用候选、认证模型到READY并运行其功能检查。下载/维护/加载和请求速度分别计时。

`software/boot/board_sd.py`是公共计划/校验实现，原始回应解析复用
`scripts/verify_sd_writer.py:responses`，SPI/UART协议保持原已验收实现。
执行器快照及通用工具各自保存，不修改已封存产物来让新任务通过。

本机100kHz实测：9,188,552字节维护工具下载3674.266秒。标称TCK不能用作实际传输速率。
公共估算采用实测速率下界和余量，UART预启动等待须长于完整编程窗口。
现行新任务维护下载监督10800秒、UART初始等待14400秒；候选监督独立设置。
空write_stdin/wait及exec外层遵守根AGENTS长等待规则。

检查日志与PID后接管同一次进程；时间估算不足时不要中止再刷。
被动UART采集器可在配置完成前、确认尚无启动字节时替换；记录旧/新owner、全局锁及转交收据。
进程退出与锁清理之间有延迟，确认原owner退出后才释放其锁。
写卡子manifest在运行中可能预置FAIL；判断完成状态时同时看父收据、进程和commands，不能因此重写。

恢复使用当前覆盖区前像和原A档案。旧OPT04恢复器是当时固定布局；本次扩展58扇区，
回退时须恢复全部58扇区及原头并核验完整前像，不能只套用旧单尾扇区常量。
只有实际执行/回读过的恢复才称为恢复PASS；保存了档案或计划不等于当前实物恢复通过。

已接受实例：OPT03/OPT04历史见 `docs/reports/OPT03.md`；本次工具及完整SD写卡见登记表所列收据。
SD维护通过不自动等于主应用功能、正常TTFT/decode、DDR故障恢复或整板生产GO。

UART速率分开绑定：维护工具500000 baud已通过本次10233条实际回应核验。主候选的精确PDS输入ce64-logic.v确认DIVISOR125，时钟合同125MHz，设计速率为1000000；这不等于CP2102物理链路已通过。500k及1M的两次主候选采集均乱码FAIL，未发任何服务命令，未观察到可验收的READY或W。Windows GetCommState和IOCTL虽回报1M，但仅证明驱动接受设置，不能测得线上速率。板卡手册标为CP2102；[Silicon Labs数据表](https://www.silabs.com/documents/public/data-sheets/CP2102-9.pdf)表12的默认速率列有500k/921600，额外速率指向AN721定制配置；此处不能把CP2102N能力套用给它，也未读取实际alias表或测量线速。当前应用链路未资格化，禁止循环改速率、重复配置/装载或修改桥接芯片NVM来试错。后续先证明真实1M路径，再接管现有配置；缺失的启动banner不回填。

2026-10-28 T27首字流式实板最终接续更正：实际部署和负向报告已完成，**SD/主候选CRAM/完整认证启动PASS，首次W数值门槛FAIL，首字A/B未执行**。唯一CID6164ceebf5f2626a61eef8f344931a1bff4c1fa0ac534a17e4526482e424a6f6，125MHz/UART115200；维护500000分开。实读卡/完整旧摘要/覆盖前像/25扩展扇区/尾到头搬移/应用/头最后/完整新物理SHA9348dcef82a737b2b7d6abd91acc08ca6c164a20f36b3561fb0a936ea3b4f471/外邻/DISARM及10225原始回应独审PASS。主配置2993.844s，配置完成到完整READY3883.474939s；本次维护CRAM1、主CRAM1、模型装载1，记录累计主配置/必然装载各3。W首次及一次有界恢复重试均STEP0/0→fffffff6=NXR_STATE(-10)，0/158080 word，无LOGITS/KV/正常TIME/METRICS；原严格数值检查拒绝。故障后仅空行/telemetry/memory，一次文档化CE会话恢复到0x307后唯一W重试仍同错，无板卡/FPGA复位或模型重载；status0x387 owner保持，原严格闲置检查拒绝，精确底层completion/算子原因UNKNOWN。先读evidence/T27/t27-first-character-board-20261028-v1/REPORT.md、VALIDATION/HANDOFF及configs/t27-first-character-board-20261028-v1.json。opt17_board_current/live已指向本次负结论，独立负向证据验收PASS不是功能PASS。主机首字/decode/DOM/RAF均UNKNOWN，不用仿真/历史填数。当前配置保留，无活动板控/采集、锁释放；禁止重启任一已结束pipeline/run_media/run_boot/windows_ab，不重写SD/重刷/reload/扫速/复位。主应用/ROM/PnR未改，Flash/NVM未写，current/opt17_current及封存离线产物不变。T27正式OPEN/O02O03 DEFERRED/T28依赖保持。只读make t27-first-character-board-verify返回负向证据验收，make board-sd-verify返回介质PASS。后续可观测性/修复候选需新的明确范围。
