# Demo V6实板已完成

先读REPORT.md、VALIDATION.json、FINAL_AUDIT.json、FINAL_POSTCONDITIONS.json和COUNTS.json。本轮唯一CID3ebbf449cb622e28baa59e02e02da20ba79a4a4b03d3278aacfa650ecbcb413a、离线EID8ef3ff0698423c55cb41c06fce036b6e1a0a8bf0d06bfbac48a602b96f517451；主源码及整套主资产保持。维护CRAM1/1、SD事务1/1、主CRAM1/1、模型装载触发/认证1/1，累计主尝试11/完整10/模型触发9。所有已成功动作已用完本轮上限，不得重启任何完成/失败run、prepare、program、media或boot执行器。

物理保留V6 READY，values0/owned45、sealed/owner/native0x307。停止灯效并保留OFF所有权，不自动释放到自动显示，不刷回CoreMark。所有本轮进程/句柄/锁已关闭。新任务先看configs/demo-v6-board-current.json及实际进程，原CoreMark正式成绩与恢复资产保持。独立CoreMark RTL任务不属于本轮，不要管理它。

新认证启动/W158080逐位、实时模型on/off、普通问答、prefill/decode各取消及下一真实请求、过期重复/非法命令/行溢出/安全超时恢复、未知动作模型reject零写已执行。prefill取消检查器修正导致下一命令间隔38s，decode约1s，如实保留。并行blink启用和交替数字读回有证据，忙时连续引脚波形/精确节拍仍NOT_OBSERVED，物理光学均NOT_OBSERVED；不能升级完整生产GO。

Fabric原生Debugger确已连接服务，但scan未发现电缆；当前ATK配置和UART工作，原生电缆路径未资格化。原始失败/无波形记录保留，不能用历史波形回填。保持供电和当前V6，之后同版服务/兼容电缆+匹配FIC可继续尝试抓取，不需要为抓取重配置；新改线须另有明确范围。store fault/NPU数值注入无安全生产入口NOT_RUN。无Flash/NVM/额外reset/reload。

只读复验make demo-v6-board / demo-v6-board-verify；运行器已经结束，不重启。数据均固定在本收据和封存离线包，不依赖C盘scratch作为验收原件。
