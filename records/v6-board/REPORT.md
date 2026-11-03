# Demo V6实板测试

核心真实模型、灯控提交、取消及后续请求链路已在同一次V6配置和认证模型装载下实际执行通过。Fabric原生服务已连接，但电缆扫描失败，无波形；用户不能现场观察，实体LED为NOT_OBSERVED。并行灯效有启停及读回证据，推理全过程的连续引脚波形/精确节拍仍未观察。全部用户要求没有整体闭合，production_GO=false。

## 身份与动作次数

源码CID `3ebbf449cb622e28baa59e02e02da20ba79a4a4b03d3278aacfa650ecbcb413a`；离线调试EID `8ef3ff0698423c55cb41c06fce036b6e1a0a8bf0d06bfbac48a602b96f517451`。1046文件封存主源码及sbit/FIC/ELF/ROM/镜像未改。PG2L200H/FBB676/-6，CPU/系统/CE125MHz，应用115200、维护500000。此前新PDS十表及SetupSlow0.000ns为离线实现结果，本轮未重做主PnR。

本轮维护CRAM尝试/成功1/1，SD更新事务/成功1/1，V6主CRAM尝试/成功1/1，配置触发及认证接受模型装载1/1。累计主配置尝试11、完整配置10、模型装载触发9。维护3673.484s、主配置3123.391s，均为同一PID一次传输，无重试。Flash/NVM、额外FPGA reset/reload、电源循环与改线均0。CoreMark正式成绩、恢复位流和原始证据复验通过且保持；未自动刷回。

## 介质与启动

实读卡CID035344534e353132869a0e00e20178c7，完整旧物理SHA77be6f6f…dcfad匹配DemoV5；按V6实际镜像重算LBA10298→10306，后移8sector。保存542008320B覆盖前像SHAbe77a836…d26f4与邻扇区后，尾到头模型搬移、每sector读回、写新应用及头最后提交。全部新物理SHAcd8cbdda5d97a6d450375e96d47468e0d1c89422eed3edfbb13be2429fdd230d、外邻不变、DISARM及10327原始回应独立审计通过。

主配置前115200原始采集已就绪，完整首次EXPECT APP、SERVICE/MODEL/capabilities/READY保存；没有补banner。认证启动13个内存span与新ELF/模型一致，承诺DDR560223489B；sealed、owner/native闲置0x307通过。本版本W一次执行，158080FP32 word逐位通过；不复用父版W。

## 应用实际结果

47条应用命令及4条启动/W命令，另2条匹配取消发送，原始RX/TX与逐chunk单调时间完整保存。10个真实模型请求：7完成、2取消、1安全超时；另有W自检。无主机语义缓存或固定关键词替代。

- 自然“打开灯。”“关闭灯。”生产`:actm 45`分别实际生成`[["led",1]]`和`[["led",0]]`，合法JSON/EOS151645；CPU报告各一次MMIO提交，mask45，值45/0，owned45，随后独立命令读回一致。真实总线AW/BRESP未抓到，CPU写合同和读回有证据，实体亮灭无观察。
- V6实际通道0/2/3/5对应A20/C19/E18/A18逐通道ON/OFF，保留其他位；逻辑active_high依据本版固件/约束，光学极性未知。`:blink 45 100 0`启动后6次读回同时覆盖0/45，owned45；保持灯效启用期间普通真实问答完成且无ACTION/新灯控授权，随后prefill/decode取消与恢复也处于此区间。没有忙时连续波形，不能将启动/前后读回升级为全过程节拍实测。
- prefill session6、decode session9均匹配CONTROL accepted、ABORT -11、REQUEST_END cancelled及READY。各自下一条UART命令为新的真实请求session8/11，均完成、prefix_hit0、零fallback；其后telemetry安全闲置。主机取消发送至完整响应分别0.1048003s、3.7129943s，包含UART/安全检查点/排空，不能作为ISR延迟。prefill因检查器修正，READY至下一命令间隔38.020936s；decode为1.0114869s，完整保留，不能声称两者均无主机停顿。
- 各已结束session重复2次取消均stale；活动中同时重复取消未测。非法命令、非法mask、4100字符输入行溢出拒绝后继续；这不是硬件FIFO或8192B环溢出压力资格。
- 合法`:timeout 1`真实请求取得ABORT -7、REQUEST_END timeout、READY；恢复1800s预算后新真实请求成功。无FPGA reset/reload。数值溢出/NPU故障和store access fault没有安全生产入口，NOT_RUN，没有非法地址访问/信任摘要破坏。
- 未知动作请求真实生成`[["reject","UNSUPPORTED"]]`及EOS；CPU ACTION_BANK UNSUPPORTED、writes0，values0/owned45。属于生产模型拒绝路径；没有把注入合成未知JSON冒充真实推理。

## 本轮物理样本

| 样本 | 板内prefix hit | 主机首可见字符s | 板内prefill s | 板内decode s | 主机至READY s |
|---|---:|---:|---:|---:|---:|
| real-model-on | 0 | 204.514146 | 204.340787 | 32.781028 | 238.105819 |
| real-model-off | 1 | 46.684522 | 46.510466 | 32.779649 | 80.274203 |
| real-question-during-blink | 0 | 70.719904 | 70.571750 | 57.455239 | 129.268635 |
| immediate-after-prefill | 0 | 78.799852 | 78.643829 | 58.821418 | 138.717478 |
| immediate-after-decode | 0 | 76.397471 | 76.240103 | 38.145659 | 115.446476 |
| real-after-timeout | 0 | 58.498933 | 58.351127 | 43.499970 | 102.973170 |
| unknown-action-model-probe | 0 | 235.868341 | 235.685550 | 39.835569 | 276.547148 |

7完成样本报告的栈高水位均11660B，成功路径guard检查通过；完整生产最大动态栈及最坏时序UNKNOWN。PMU/TRANSFER原数值在PERFORMANCE及原始UART；IRQ专属轮询次数、pending→ISR延迟及灯效节拍偏差没有安全遥测或波形，UNKNOWN。不能用历史RTL数字填充，也不能将冷/暖前缀样本混作性能对照。

## Fabric与未测项

实际执行PDS2024.2/build178169 cdt_js/cdt_dbg。服务版本匹配/连接通过，dbg_scan_chain在open_cable时报No cable was found，尚未到器件/FIC/核心扫描。ATK在Windows经已验证CMSIS-DAP/HID下载；原生服务在Linux/WSL且只见USB root hub。Windows注册表/常见目录未发现PDS服务；这是当前主机/驱动路径及电缆兼容性缺口，不证明V6调试核或UART故障。保留fabric-preflight原始日志，未执行dbg_program或调试复位。

LED提交/BRESP、NPU pending→ISR→登记→消费→ACK和取消全过程原生波形全部NOT_RUN。未来用同版原生服务及Pango兼容电缆保持供电连接此配置，匹配FIC后可尝试，不要求重烧。260x1024/预触发256且TU4存储资格造成不等间隔，未来也不能按每点8ns解释长链路。

store fault独立诊断需要新受信任ROM/固件、受控拒绝写测试从设备、精确MEPC/MTVAL/cause7检查及匹配FIC；不在本次生产封存镜像中补洞或额外配置。

## 失败与最终现场

原始首个维护包装路径准备错误、主控制器媒体收尾锁竞争、采集模块依赖遗漏均发生于相应物理动作前；检查器取消READY语义及最终memory仅摘要表示的两处拒绝保留并独立修正。没有因此重刷、重写或重发已完成请求；全流程使用实际收据记账。主机脚本变体/接管日志全部保留。

最终blinkstop→明确OFF→读回values0/owned45→memory/telemetry READY、sealed/native闲置0x307。全部本轮Windows进程退出、UART句柄及串口锁释放、全局板锁可获取；保留V6，CoreMark恢复资产保持。只读`make demo-v6-board-verify`，不得重启任何历史run/prepare/program/恢复执行器。T27及生产GO未因本轮局部验收闭合。
