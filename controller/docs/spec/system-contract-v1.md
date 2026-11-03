# T08 系统合同 v1

version=system-v1；producer=T08；consumers=T09/T10/T11/T12/T13/T14/T15/T17/T18/T19/T21/T24/T27。
本合同选择 **SIM_SELECTED：Coral RvvCoreMiniAxi RVV**，主控仍为 VexRiscv。
输入沿用 [范围 v1.1](project-scope.md)、[应用模型锁](application-v2-model-lock.json)、
[数值 v1](numeric-v1.md) 和 [T07 实测](../reports/backend-sim-feasibility.md)。
选择状态不代表 FPGA_QUALIFIED，正式资格仍 UNCONFIRMED；F01/O01–O04 未激活。

## 选择依据与实现边界

| 决策维度 | 已有证据 | 选择与待交付内容 |
|---|---|---|
| 正确性 | T07 121 组整数、122 组 FP32 检查通过；真实 Q/K/gate/down M=1/4 全行、head 代表块 | 沿用 W8A8 g64；V/O/up、完整 head 和通用尾块由 T15 验收 |
| 外存 | 128-bit/ID6 主口真实读权重、scale/bias 并写结果，超 32KiB TCM | 权重从 DDR 流式读，主控只上传程序、参数及量化 activation；T14 实现调度 |
| RV32 接入 | T06 已验原生 AXI 从口 TCM 装载与 CSR 启动/状态 | T13 实现 RV32 总线到 128-bit 从口桥接，lane/WSTRB/响应必须保留 |
| 软件覆盖 | T05 桌面参考覆盖整网语义；T07 仅线性探针 | RV32 C 执行 attention/vector 和入口量化，T11/T12 验收；不假定 VME/原生 attention 支持 |
| 性能代价 | 当前串行访存，读写各一笔 outstanding；含审计的 M=1 K 投影 ideal 为 197,659 cycles | 接受功能优先仿真路线；T27 冻结实测目标。T07 的线性外推不作为 token/s、整网耗时上下界或加速比 |
| 移植范围 | 8KiB ITCM、32KiB DTCM、原生控制及已锁定工具链 | 单一 Coral 路线，保留 CPU C 数值回退；不建设第二套 64B 描述符硬件 |

固定 commit `382b5c12030ad8eb74ab8deafb2529301faeab16`、VLEN=128、VME=false；
GCC/RTL 身份沿用 T06/T07。板上 SRAM、时钟门控、PDS 适配以及面积/Fmax 由 T22–T24 验收。
若 T24 无法映射，先缩配置，再按既有条件重开 T08/F01，不在本卡同时开发备选。

## 地址与启动

[memory-map-v1.json](memory-map-v1.json) 是地址、长度、权限、缓存属性的唯一数值来源。
所有区间为左闭右开，32 位无符号物理地址，小端；计算 end/span 时用至少 64 位并先检查溢出。

| SoC 范围 | 用途 | 属性/接续任务 |
|---|---|---|
| 0x00010000–0x00020000 | 64KiB ROM，reset PC=0x00010000 | 只读可执行；T09/T17 实现 |
| 0x00020000–0x00030000 | 64KiB boot SRAM | CPU 私有非缓存，启动栈与下载暂存 |
| 0x10000000–0x10001000 | UART/定时器/仿真诊断 | Device；保留 T03 +0x00…+0x20 含义，T17 扩展 RX |
| 0x10001000–0x10002000 | 传感器/GPIO 预留 | Device；T20/T26 定义寄存器，未实现地址拒绝 |
| 0x10002000–0x10003000 | SD/SPI 预留 | Device；T18 定义寄存器，未实现地址拒绝 |
| 0x20000000–0x20040000 | Coral 从口 aperture | Device；只解码下表三个本地区间，洞返回 DECERR |
| 0x80000000–0xA8000000 | 640MiB 模型权重/scale/小参数 | 非缓存；装载期 loader 可写，校验封存后 CPU/Coral 只读 |
| 0xA8000000–0xAC000000 | 64MiB KV | 非缓存；按会话独占写 |
| 0xAC000000–0xB4000000 | 128MiB activation/工作区 | 非缓存；CPU/后端轮换所有权 |
| 0xB4000000–0xB8000000 | 64MiB CPU 程序/堆/栈 | 可缓存；应用入口 0xB4000000，栈顶 0xB8000000，预留最高 64KiB 栈 |
| 0xB8000000–0xBA000000 | 32MiB tokenizer/文本 | CPU 只读可缓存；loader 装载后封存 |
| 0xBA000000–0xBC000000 | 32MiB 共享任务/日志/传输区 | 非缓存；无固定 64B 描述符要求 |
| 0xBC000000–0xC0000000 | 64MiB 预留 | 不映射、不分配、不允许推理访问 |

| Coral 本地地址 | CPU SoC 地址 | 意义 |
|---|---|---|
| [0x00000,0x02000) | [0x20000000,0x20002000) | ITCM，程序及入口 PC 所在区 |
| [0x10000,0x18000) | [0x20010000,0x20018000) | DTCM，参数/activation/栈/结果状态 |
| [0x30000,0x31000) | [0x20030000,0x20031000) | 原生 CSR；本合同仅使用 +0/+4/+8 |

CPU 访问 Coral 从口时桥接执行 `local = soc - 0x20000000`；入口 PC 必须是 ITCM
内 4 字节对齐的**本地**地址，不能写 0x20000000 别名。Coral 外存主口 DDR 地址与
SoC DDR 地址相同，不减 aperture 基址。RTL 已有 TCM decode；SoC 权限过滤由 T13/T14
实现，不能宣称 Coral 自带内存保护。Coral 只读 weights/kv/workspace/shared_io，
只写 kv/workspace/shared_io；不能访问 CPU 私有代码、tokenizer、ROM/MMIO 或预留区。
整段 buffer 必须落在同一个合法分区，跨界、空洞、地址回卷均拒绝。

T03 的 reset=0x80000000 与 T07 的 Y=0xA0000000 是历史测试布局；前者现属模型区，
后者现为只读模型区，不能直接用于系统集成。保留历史测试不修改，T09/T13/T14 必须
显式迁移并重验。T17/T18 的应用装载区是 CPU private；PRELOAD/PROTOCOL_BOOT 分开配置，
后者禁止预置目标应用和模型，以真实 UART/SD 字节和校验成功才允许跳转。

## 缓存、所有权和错误恢复

只有 CPU private/tokenizer 可缓存；共享可写数据统一非缓存，不建立缓存属性冲突别名。
桌面 API 中的物理地址由受检查 arena 解析，不能把 RV32 高地址经有符号 int 扩展。
CPU 发布输入前完成存储屏障和总线写完成，再交所有权；后端拥有 buffer 时 CPU 不读写输出，
也不修改输入。只读权重可共享；buffer 间除明确的只读模型别名外不得重叠。

完成条件是程序正常 halt、fault=0、匹配 session/sequence 的成功结果记录，以及全部外存
写响应结束且主控可见。`halted` 单独不代表 API 成功。若平台有异步桥，必须证明排空完成。
超时/AXI 错误/fault 后标记上下文 FAULTED，拒绝新提交，全部输出视为无效；保留地址、请求
身份和计数。恢复先隔离新请求、排空 outstanding 或通过经验证的总线隔离丢弃响应，再复位
Coral、重新装载程序，增加 session，清空逻辑 KV 长度；未能保证隔离时保持故障态。
不能仅清零软件 busy 后复用仍被硬件写入的 buffer。T13 必须在实际 CPU＋后端验证这些条件。

普通 FENCE 不等于 D-Cache clean。下载 CPU executable 涉及写回/失效和 FENCE.I；采用
T09 实际验收的机制，T17/T18 再测协议启动。T08 只定义要求，不提前认可 Cache/FPU 行为。

## 容量、模型包与移交

T05 逻辑 W8+scale+小参数为 525,120,000 bytes，640 token FP32 KV 为 15,728,640 bytes。
640MiB/64MiB 窗口能容纳这些逻辑量，但不是 T10 实际包大小或 T12 峰值内存验收；
不得把窗口剩余空间写成已验证的运行时余量。默认请求 input≤512、new≤128、总 KV≤640。
长上下文扩展须升版和重验，不能仅因 64MiB KV 有余量即暴露能力。

T05 负责逻辑数值/张量，T08 冻结 [软件 API](backend-contract-v1.md) 和逻辑 view；
T10 负责包 magic/version、layout_id、目录、offset/length、校验和实际物理排列。
T08 不分配一个未经 T10 验证的物理 layout_id。运行时通过包 adapter 获取合法张量 view，
拒绝未知物理布局；不能将包 offset 当 CPU 指针或 Coral PC。共享 embedding/head 必须同一份
Wq/Sw，bias/norm FP32；禁止整模型解量化或复制转置，允许计时的小块暂存。

T10 接模型布局/容量；T11 接完整 C 数值参考；T12 接 session/调度/回退计时；T13 接地址/原生
控制/所有权；T14/T15 接分块/内核；T19 接累计层验证；T24 决定 FPGA_QUALIFIED。
任何合同变更记录 version、reason、producer、consumers、affected_tests，并重跑 `make t08`
与对应的包、驱动、RTL、数值回归。
