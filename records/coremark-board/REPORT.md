# 当前 RISC-V 实板 CoreMark

实板两组标准种子均通过，性能成绩 **195.543209 CoreMark**，
**1.564346 CoreMark/MHz**。频率依据为同次实现的实际 PLL 配置 125MHz；
没有独立仪器频率测量，未提交 EEMBC 官方数据库。

| 运行 | 次数 | 原始64位周期 | 125MHz名义秒数 | 标准CRC | 独立最终CRC |
|---|---:|---:|---:|---|---|
| 性能：0,0,0x66 | 5000 | 3196224524 | 25.569796192 | PASS | bd59 |
| 校验：0x3415,0x3415,0x66 | 5000 | 3207338652 | 25.658709216 | PASS | f440 |

两组运行使用同一个二进制、相同编译参数和存储条件，均超过10秒。
计时取自真实 CPU mcycleh/mcycle 稳定64位读取；原始UART打印值、主机接收时间与周期一致性已独立核对。
末尾原生NCE2完成帧也已按实际RTL格式核对：type=2、tag=0、exit_code=0xc021、CRC32通过。
初版纯ASCII检查器因该合法二进制完成帧拒绝，原代码和失败日志保留；修正帧边界后原始数据复验及12项篡改拒绝通过，没有重新执行实板。
官方五个算法文件及 coremark.h 原样保持，固定上游提交1f483d5b8316753a742cbf5590caf5bd0a4e4777。
编译器：riscv32-unknown-elf-gcc (xPack GNU RISC-V Embedded GCC x86_64) 14.2.0；O3，无LTO，无fast-math。

代码在 DDR 0xb4000000 执行，2000字节工作集位于既有片上SRAM栈；
I/D Cache各16KiB、两路、32字节行，D Cache写穿，单上下文，DDR用户接口与CPU时钟1:1。
完整CPU/cache/SoC RTL与原demo-v5逐文件相同；专用ROM复制并逐字节读回CRC检查基准程序后执行。
修改范围仅为移植层及启动程序。NPU未参与CoreMark。

新PDS2024.2/build178169在PG2L200H/FBB676/-6完成原125MHz约束实现，
十张时序表、87引脚逐项绑定、route零未布线/零过用和原资源预算通过。
Setup/Slow WNS +0.035ns；routed 70726 LUT、47232 FF、
129 DRM物理site、43 APM。
CPU单独LUT未分离，完整SoC口径CoreMark/LUT=0.002764799；不以此冒充CPU单独口径。
单个通过工作点不证明Fmax。

- 源码CID：78f2636b1cfb5619b3b5932a02443e19d9e0536b2c6fea097bc6a12b8089fc36（1042文件）；父demo-v5 CID20a0545a394a86a5df98d8d91aa714bbb7870fbe79c80ba0656b5a187ab67266。
- 实现EID：623e811cf2c3c36408522a58bb34bf2515ff6dae5ce297437c0eeb9c18b4f30d。
- 实板证据EID：25ef315ad6e7649cb5701dd64d9282c5a1652b756ffe87c1dc08301e0422e57b。
- 位流SHA256：d4a71355cdf9869e712337f49f79937c3733bd06546b4374ac5e484cae277f42。
- 原始UART：capture/uart.bin；连续字节/主机单调时间：capture/chunks.jsonl。
- 完整原数值与独立检查：VALIDATION.json；固定输入绑定：EVIDENCE_BINDING.json。

本轮主CRAM共两次传输尝试：首次在约70%时随旧监督会话退出而中止，没有原生完成收据；
该失败及两次零字节接收记录保留。纠正进程生命周期后，以已通过退出存活验证的独立Windows进程
重传同一冻结SVF，一次完成原生ID/CRC/DONE检查。有效115200被动采集从该次下载前完整覆盖启动与两组测试，UART发送0字节。
没有SD/Flash/NVM写入、额外reset/reload或模型装载。历史累计完整主配置9、主配置尝试10、模型装载8。
按用户选择，现场保留基准程序并停在成对运行结束后的空闲循环；原演示位流、应用、模型SD及所有旧报告保持。
恢复演示需另行恢复原配置并加载模型。

初次用户暂停、两次批处理检查点恢复拒绝、报告器辅助路径错误及首次采集共享冲突完整保留；
报告处理已独立纠正，无需重跑已完成PDS。后续采用已验证的完整工程流程重建，
没有改CPU、降频或放宽约束。本结果完成当前CPU的有界正式CoreMark测量；
完整T30/PHY/CDC/RDC、T27、生产最大栈及完整模型性能等既有未测范围保持，production_GO=false。
