# 当前 RISC-V 正式时长 RTL CoreMark

完整5000次双种子仿真通过。**RTL CoreMark 256.203374，CoreMark/MHz 2.049627**，
按125MHz参考频率换算；每组模拟CPU运行时间均超过10秒，官方CRC和独立最终CRC全部通过。
结果来源为RTL仿真，DDR/互连条件见下文；未提交EEMBC数据库。

| 运行 | 迭代次数 | 64位周期计时 | 周期/次 | 125MHz模拟秒数 | CRC |
|---|---:|---:|---:|---:|---|
| performance | 5000 | 2439468262 | 487893.6524 | 19.515746096 | 官方PASS；final bd59 |
| validation | 5000 | 2447014668 | 489402.9336 | 19.576117344 | 官方PASS；final f440 |

主机仿真墙钟耗时5838.464秒（97.308分钟）；
这是执行速度，不作为CoreMark分母。完整启动/双seed执行累计4889578925周期，
退休3061466748条指令；累计周期跨过2^32，原移植层采用mcycleh/mcycle稳定64位读取。
所有算法在CPU RTL上真实执行，未通过主机计算替代DUT输出。

## 测量合同

源码CID `78f2636b1cfb5619b3b5932a02443e19d9e0536b2c6fea097bc6a12b8089fc36`，与实板测试封存源码逐文件一致；全部1042文件未改。
直接复制已验收实板的5000次配对程序、ELF和ROM，文件逐项SHA256核对，二进制完全相同；
不是更改计时频率、缩短轮数或重用100次日志。GCC14.2/O3，无LTO、无fast-math，
CoreMark固定上游算法未改，2000B工作集在生产片上SRAM栈，代码从DDR地址执行。

Verilator新编译真实T09CPU、I/D Cache与生产SRAM RTL，LOCAL_READ_PIPELINE=1；
I/D Cache各16KiB、2路、32B行，D Cache写穿。测试路由器、程序DDR、platform-ready与UART为行为模型；
DDR读写配置均为3周期响应延迟，未包含完整生产桥接/仲裁/DDR适配链路及物理PHY。
本轮保持上次短测的模型条件，以便比较迭代次数影响。
125MHz是周期换算参考，仿真器时间步长与主机墙钟均不用于声明独立实测频率。
测试驱动仅新增主机侧UART流式落盘与进度观察，模拟时钟/握手逻辑未改，补丁在sim/harness-observation.patch。

## 与既有结果并列

| 口径 | 每组次数 | CoreMark/MHz | 按125MHz的迭代/秒 |
|---|---:|---:|---:|
| 本轮正式时长RTL | 5000 | 2.049627 | 256.203374 |
| 历史RTL短测参考 | 100 | 2.049425 | 256.178083 |
| 历史完整实板 | 5000 | 1.564346 | 195.543209 |

正式时长RTL相对实板的吞吐差为+31.021%。
两边现在使用相同5000次二进制，剩余差距仍需要完整生产访存链路/真实等待的成对归因，不能仅凭该差值把全部开销归给DDR。
本次不替代实板195.543209 CoreMark的物理测量记录，不宣称完整SoC/PHY或新的板端收益。

## 验收与复验

核对官方seed/list/matrix/state CRC、独立主机原算法5000次final bd59/f440、
原始UART秒数/速率与64位周期一致性、完整启动载荷CRC与CPU退出0xc021。
八项错误CRC/模式/迭代次数/载荷/周期/正式标记/截断证据均被拒绝。

- 原始UART：execute-pair.stdout.log；DUT结构化输出：result.json。
- 原始执行命令、超时上限、退出状态和主机耗时：execute-pair.COMMAND.json。
- 输入身份：SOURCE_FREEZE.json、FIRMWARE_BINDING.json、sim/INPUTS.json。
- RTL仿真器SHA256：`5e507a775702bdd9b7a16d11a13a456fc842e927dbdacfefda25e76749d4d556`。
- 实板相同程序SHA256：`12b5fef7c11a21b9a2e9c2507a4e53b5893ddd7da4b0b1a836f0beb8265d9403`。
- 独立复验：`make coremark-rtl-formal-verify`；完整数值见VALIDATION.json。

本轮无板卡/串口/PDS/下载/SD/Flash/NVM/reset/reload动作，当前物理配置和历史成绩保持。
全部本轮运行器已退出，禁止重启run_once.py。完整生产总线/PHY时序、Fmax和生产GO不由本轮关闭。
