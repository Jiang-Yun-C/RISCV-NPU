# 当前V6 CPU独立最高频率评估（2026-11-03）

最高实际目标频点通过 **231 MHz**；最近更高的已测失败频点为 **232 MHz**。这是PG2L200H/FBB676/-6、PDS2024.2/build178169、每频点4个seed的有限布局布线搜索结果，不是全部可能seed的全局极限或实板超频结果。

CPU保持逐字节不变：5级RV32IMF、I/D各16KiB两路LRU缓存、32B行、256项BTB、FPU及V6精确store/CSR/IRQ。父源码CID `3ebbf449cb622e28baa59e02e02da20ba79a4a4b03d3278aacfa650ecbcb413a`，CPU SHA256 `76975e1d69cbe2f105b23208225f2c34c5bbe5c3911edad3ed1a3156f4f17075`；新执行EID `0ec17c316d65eda5e617059abfedb040ece1826f3b41c7670643c5ca4b5d0ea3`。未重新生成CPU或改动流水级。DDR、NPU、外设、ROM存储阵列、分析仪与PLL均未纳入本次顶层。

| 目标MHz | 最佳seed | Setup/Slow WNS ns | 全十表 | 原生setup估算MHz |
|---:|---:|---:|:---:|---:|
| 150 | 14 | +0.685 | PASS | 167.1794 |
| 200 | 13 | +0.358 | PASS | 215.4244 |
| 220 | 12 | +0.168 | PASS | 228.4441 |
| 225 | 15 | +0.128 | PASS | 231.6728 |
| 228 | 15 | +0.035 | PASS | 229.8345 |
| 229 | 13 | +0.090 | PASS | 233.8199 |
| 230 | 15 | -0.110 | FAIL | 224.3235 |
| 231 | 12 | +0.097 | PASS | 236.2947 |
| 232 | 15 | -0.003 | FAIL | 231.8386 |
| 235 | 15 | -0.102 | FAIL | 229.4985 |
| 250 | 14 | -0.314 | FAIL | 231.8034 |

各频点均独立从同一CPU RTL编译/综合/映射，PnR seeds12–15、groute2、performance、hold fix/logic optimize开启；每个频点2个seed同时运行，最多3频点并发，关闭首个收敛seed即停止。共44个seed，全部完成；每个选定结果route unrouted/overused=0、十表text/XML逐字段相等、实际Clock Summary周期与目标相符。资源与完整原件均按频点保存，不能把综合估算当作布线通过。

231 MHz最佳结果最差setup为+0.097ns，hold slow/fast分别+0.057/+0.043ns。关键路径起点 `cpu/T09IBus_fetchPc_pcReg[3]/opit_0_L7Q_perm/CLK`，终点 `response[33]/opit_0_L6Q_perm/I3`；含测量边界，须按该边界解释。完整路径见CRITICAL_PATH.txt。实际布局资源含包装：5169 LUT、3938 FF、15 DRM物理site、8 APM；没有将包装开销冒称为CPU纯资源。

CPU原接口共有572bit，超过封装400用户IO，因此使用6pin串行寄存包装：115bit寄存输入（含CPU reset）、456bit并行捕获/串行读出响应。60个CPU端口逐一连接，全输入动态可控、全输出可观察；仅4个包装pad输入起点与scan_out pad终点例外，CPU内部、输入寄存器到CPU、CPU到捕获寄存器和CPU reset恢复/移除路径正常计时。边界用于布局布线测量，未做CPU运行或CoreMark测试。

check_timing无no_clock/不展开时钟/组合环/锁存器等内部缺口。4个无input_delay输入及1个无output_delay输出均为上述明确排除的扫描pad；不需要虚拟时钟。未显式设clock uncertainty，原生setup路径实际为0.050ns，保留PDS默认值。最小脉宽及两角setup/hold/recovery/removal全部按实际报告验收。

原生setup估算最高为236.2947MHz，只是对应布线周期/WNS的估算；目标频点间的映射、布局存在波动，失败频点不能证明所有更高频点均不可能。固定布线改频STA探针未资格化：旧ADF重载导致约束未生效、原生TA GUI未导出报告及工具选项不匹配均保留失败收据，没有把它们计为通过。首批汇总错误拒绝预期“无虚拟时钟”已由新只读分析纠正，原ERROR_PRESERVED不改写，无重复PnR。

本轮没有生成位流或硬件/串口/SD/Flash/NVM/reset/reload动作，现有V6实板125MHz配置与封存资产保持。全CPU独立时序不能替代整SoC/DDR闭合或实板频率资格，T27 OPEN/production_GO=false保持。

只读复验：`python3 -B variants/demo_v6_fmax_20261103_v1/verify_cpu_v2.py` 或 `make cpu-fmax-verify`。不要重启已完成run脚本；频点目录拒绝覆盖，所有失败/探针/更正原件保留在固定evidence目录。

封存后只读验收更正v2：首版验收器直接比较Python tuple与JSON list，误拒绝相同序列化内容。v2先规范化JSON后逐项重核全部11频点/44seed、源/时钟/十表/资源/关键路径和执行身份，PASS；首版报告、验收器、manifest及失败记录原样保留。没有重跑EDA或修改测量结果。
