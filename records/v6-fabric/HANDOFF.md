# Demo V6 Fabric 接续

当前主配置仍为V6 CID3ebbf449…413a，125MHz/UART115200，READY、LED values0/owned45、sealed/owner/native0x307。ATK原生Fabric通路已实际抓取三组波形，详见REPORT、VALIDATION、CAPTURE_BINDING、WAVEFORM_VALIDATION、UART_VALIDATION和FINAL_POSTCONDITIONS。目录日期为发布锚点，实际执行2026-11-03。

所有本轮自有采集、PDS服务、软件桥、Windows HID及串口已退出并释放锁。主配置及模型保留；本补充阶段编程/模型装载/SD/Flash/NVM/FPGA reset/reload均0，累计主尝试11/完整10/模型触发9。原实板收据和CoreMark恢复证据不变。

只读复验：

```bash
make demo-v6-fabric-verify
make demo-v6-irq-verify
make current-baseline
```

实际重新连接用 `make demo-v6-fabric-connect ARGS='--run-id <新ID>'`。先检查当前锁、SESSION/PIDS/FINAL及实际PID；已有活动连接先接管，不能重复启动。新入口打开原生PDS GUI与受保护ATK通路，不重新下载、不打开UART；GUI选择Pango Virtual Cable和本次端口、导入精确FIC。操作详见 `docs/spec/demo-v6-fabric-atk-xvc.md`。历史software_probe/host_bridge/gui/uart_request等脚本只用于原始审计，不直接重启。

LED波形完整覆盖store/BRESP/输出改变；NPU窗口覆盖pending/ISR登记/主消费/ACK/owner释放，pending W1C未采到；取消窗口覆盖取消登记/UART消费，完整ABORT/REQUEST_END/READY和后继请求由UART证明。不要把这些写成全生命周期都在一段波形里。TU4非等间隔、VCD100ns显示轴不能换算物理延迟。实体光学NOT_OBSERVED，store fault/NPU数值注入NOT_RUN，production_GO=false。

四次采集尝试（首个2048bit读出限制FAIL保留，后面三次导出PASS），UART元数据冲突及TX前失败、缺失清理脚本、软件探针失败和监督转交均已封存。普通取消后没有reset/reload，下一真实请求0.103秒后发出并完成；不能因历史失败重复配置、写卡或装载模型。
