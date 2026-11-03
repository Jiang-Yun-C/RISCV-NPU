# Demo V6离线接续

本轮离线资产已交付，应用端到端验收OPEN。先读REPORT.md、VALIDATION.json、REQUIREMENTS_MATRIX.md与NEXT_BOARD_PLAN.md。源码`variants/demo_v6_irq_20261102_v1/source`，CID `3ebbf449cb622e28baa59e02e02da20ba79a4a4b03d3278aacfa650ecbcb413a`；调试EID `8ef3ff0698423c55cb41c06fce036b6e1a0a8bf0d06bfbac48a602b96f517451`。完整源码1046文件、生成器/三补丁/所选RTL新重建一致，精确store异常/机器CSR和NPU/UART/mtime应用调度已实现；旧16KiB两路LRU/BTB保留。

新PDS+Fabric260x1024实际位流完成，seed12、125MHz十表PASS、SetupSlow0.000ns、72889LUT/50068FF/137DRM物理site/43APM、87脚不变。权威PDS结论为PDS_RESULT.json及pds-closeout-r2；pds-debug-r10/STATE中的FAIL是route结束后错误helper路径的监督器错误，不能重启它。pds-closeout-r1旧解析器不支持长JTAG名换行的失败也保留，v2原始表/XML逐项检查及三负例通过后才生成位流。同一routed ADF，没有新PnR。映射ROM两读副本各16384字完全等于新认证ROM。

完整真实Qwen在主机生产C新生成/取消与后续请求通过；生产CPU/CE/SFU/UART/timer局部并发三组成对及数值故障恢复通过；26例生产协议使用明确合成模型/IO与IRQ-on通知替身。完整新CPU/NPU Qwen整请求灯效/取消/READY、实板、波形、实体LED与完整生产最大动态栈均未验收。不能把RV32重放本轮新模型输出字节冒充完整CPU/NPU实时推理。production_GO=false。

本轮没有活动DUT、EDA、板控或串口采集器；其它独立对话任务不在本轮管理范围。不重启历史完成/失败流水线。当前CoreMark物理CID78f2636b1cfb5619b3b5932a02443e19d9e0536b2c6fea097bc6a12b8089fc36与配置9/尝试10/板端模型装载触发8保持，本轮物理操作0。SD镜像只在主机生成，Flash/NVM未写。`current/`、物理绑定、父版、旧证据不动。

只读`make demo-v6-irq`/`make demo-v6-irq-verify`，或便携包`python3 -B verify_delivery.py`。下一阶段须用户给新的明确板卡执行范围，再按NEXT_BOARD_PLAN接续；目前不要打开串口、下载、写介质、reset/reload或板端装载模型。
