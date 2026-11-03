# T04 外存仿真合同 v1

version: 1；producer: T04；consumers: T06/T07/T09/T13/T14/T17/T18/T23。
变更原因：替代临时一拍理想 RAM，为 CPU/后端联调提供可复用的非理想访存环境。
变更接口、地址计算、装载或延迟策略后，至少重跑 `make t04-acceptance`。

## 入口与资格

```bash
make t04                 # 完整独立构建、正向矩阵、负例、项目回归
make t04-acceptance      # 同一完整入口；每次生成新 run-id
make t04-test            # 仅检查镜像装载，不需要 VCS
```

使用 T01 锁定的 VCS X-2025.06 与用户级 Python；不需要 PDS、DDR IP 或板卡。
`configs/t04-memory.json` 记录已验收的配置；运行器拒绝配置与固定测试台不一致。
每次在 `build/T04/<run-id>/` 重编译 32/64 位模型和复位测试；`evidence/T04/<run-id>/` 保存
源码、配置、工具身份、命令、原始退出码、镜像、逐拍总线 CSV、VCD、独立检查结果。
预期失败单独保存于 `evidence/T04_NEGATIVE/`，保持 FAIL 状态。

这是 AXI 行为环境的验收。没有执行 CPU、后端算子、真实下载协议或厂商 DDR 控制器；
仿真周期、墙钟时间和吞吐均不能作为板级 DDR 或模型推理性能。

## soc_core 的共享边界

```text
tb_soc   -> soc_core -> ext_mem (axi4_if.master) -> soc_memory_env -> axi_sparse_mem
fpga_top -> soc_core -> ext_mem (同一接口)       -> T23 DDR 用户口适配器 -> DDR IP
```

`rtl/interfaces/axi4_if.sv` 是无仿真依赖的逻辑边界；`tests/soc/soc_memory_env.sv` 是可复用的仿真连接。
`soc_core` 应包含 CPU、ROM、MMIO、后端及片内互连，将共享外存事务收敛到此主端口；两种顶层复用
同一个 core。时钟、低有效同步复位、UART/中断等普通 SoC 引脚不进入内存模型。
`tb_soc` 的时钟/复位/外设 BFM、镜像装载和错误注入仅属于测试台；`fpga_top` 负责物理引脚、
时钟/复位生成和 DDR 初始化。跨时钟桥、宽度转换及真实 DDR 用户口在 T23 确认后实现。

T03 当前仍是 `t03_soc`＋简单 I/D 总线临时 RAM，尚未重构为以上 `soc_core`，也未接入本卡 AXI。
T09/T13 接入时实现并独立验收该桥接；本卡没有用 BFM 替代 CPU 后宣称 SoC 联调通过。
`tb_axi` 实际使用 `soc_memory_env` 验证这个连接边界。

## AXI 子集与排序

| 项目 | 合同 |
|---|---|
| 地址 | 32 位物理地址；内部计算升为 64 位，禁止溢出/截断别名 |
| 外存窗口 | `[0x80000000, 0xC0000000)`，容量 1GiB，设计假设，待 T23 实物核定 |
| 数据/ID | DATA_W 支持并测试 32/64；ID_W 默认 4；其他 ID 宽度尚未执行验收 |
| 未完成事务 | 每方向最多 8 笔，直到 B 握手或 RLAST 握手才释放；W FIFO 为 16 拍 |
| 五通道 | AW/W/AR 独立接收；W 可先于 AW；R/B 在 VALID 且未 READY 时保持有效及负载 |
| 排序 | 写数据按 AW 顺序配对；B 按 AW 顺序，R 按 AR 顺序且不交织；回显 ID，重复 ID 合法 |
| 突发 | INCR 1–256 拍，FIXED 1–16 拍，WRAP 2/4/8/16 拍；WRAP 起始地址必须按传输大小对齐 |
| 字节传输 | little-endian；byte/halfword/word、64 位 doubleword；窄传输的 lane 和 WSTRB 生效 |
| 非对齐 | INCR 首拍和 FIXED 的有效 lane 从 AxADDR 到该 transfer 对齐结束处；后续 INCR 拍按 AxSIZE 对齐 |
| 边界 | 每个突发不得跨 4KiB；恰好结束于页末合法，下一页用新的请求 |
| 完成 | 每个 AW 恰好一个 B；每个 AR 恰好 AxLEN+1 个 R，最后一拍 RLAST；B 出现前写数据已提交 |

接口省略 LOCK/CACHE/PROT/QOS/REGION/USER，表示普通、非独占、无属性区分的内存访问。
不支持独占访问、ACE 一致性、原子操作、读重排或写数据交织。后续桥接不得静默丢弃具有语义的属性。
全局按序响应属于合法 AXI 策略，但不能据此认为未来控制器一定全局按序；下游应遵守其实际 ID 规则。
AXI 基础协议参考 [Arm AMBA AXI/ACE IHI 0022H](https://developer.arm.com/documentation/ihi0022/h/)。

## 延迟、错误与复位

固定模式仍有 2 拍响应调度延迟，并在测试主端施加 B/R 反压。随机模式为 AW/W/AR READY 独立
选择是否开放，并将 B/每拍 R 的调度延迟设为 0–9 拍；响应 FIFO 和接收方反压可继续增加实际等待。
模型使用实例内 xorshift32，主端 READY 使用独立 PRNG；不会调用全局 `$urandom` 影响其他组件。
seed 仅改变时序，数据向量使用固定 seed 4004。重复 seed 1 的完整 CSV 必须逐字节相同，seed 7 必须改变时序。
`max_delay` 允许 0–65535，验收值 9；不承诺随机模式的最大服务周期，外部测试必须保留超时。

地址请求握手时检查整个 burst，并锁存错误注入配置。响应优先级：窗口外/地址溢出 DECERR(3)，
非法 size/burst/4KiB 边界 SLVERR(2)，注入错误，最后 OKAY(0)。
`inject_enable`、含首尾的 `inject_start/end` 与 `inject_resp`(2 或 3) 可注入整笔错误，任意传输字节
与范围重叠即匹配。读错误仍完成全 burst，数据为 0；写错误仍消费指定数量的 W，但整笔不改内存。
这是一种便于验证的模型错误策略；不能推导真实 DDR 错误的部分写入或恢复保证。
非法请求的错误响应是模型的诊断扩展，并不使跨 4KiB 等请求成为合法 AXI。

WLAST 过早/缺失、合法写请求的越 lane WSTRB、有效控制或活动写 lane 的 X 值直接 `$fatal`；
运行器同时检查退出码、通过标志与观测内容，防止 VCS 在 `$fatal` 后返回 0 被误判为通过。
复位清除所有队列、响应和 PRNG 时序状态，放弃未完成事务，**保留已提交的外部内存数据**。
复位中途写可能只提交前面若干拍；系统必须隔离/复位相应主端后再继续，不能假定复位具有回滚语义。

## 分页与镜像

`sparse_memory_pkg` 按 4KiB 页面按需分配 two-state byte 数组，用 64 位页面号索引。
未装载/未写入字节返回 0，不分配页面。BSS 清零只遍历已分配页并清除相交字节；未分配区天然为 0。
没有每次测试清零的 1GiB 四态数组。零初始化是本模型定义，不代表真实 DDR 上电内容。

```bash
npu-python tests/models/prepare_image.py --mode PRELOAD --format bin \
  --image app.bin --base 0xB4000000 --entry 0xB4000000 --output build/app-image
npu-python tests/models/prepare_image.py --mode PRELOAD --format elf \
  --image app.elf --output build/app-elf
npu-python tests/models/prepare_image.py --mode PROTOCOL_BOOT --output build/empty-boot
```

输出目录必须尚不存在且路径不含空白。入口输出至 `image.json`，模型本身不会写 PC 或启动 CPU。
BIN 必须给出合法基址、文件内且 2 字节对齐的入口；是否支持压缩指令由后续 CPU/固件合同另验。
ELF 只接收 little-endian ELF32、RISC-V、ET_EXEC；逐段检查 PT_LOAD 的 filesz/memsz、文件边界、
地址范围、alignment、段重叠与虚实地址一致，拒绝动态/解释器镜像。入口必须位于有 PF_X 的
文件支持字节内，不能位于 BSS。ELF 不修改 CPU ISA/ABI 设置，调用方还需做相应兼容检查。

每个文件段生成独立 BIN，BSS 用 `Z address length` 范围表示。`load.plan` 的 B 行指定
地址、长度和二进制路径；SV 用 `$fread` 每次读取最多 4KiB，不做逐字节文本解析。
`image.json` 保留源镜像和段哈希。运行器的 artifacts 再保存所有输入及输出哈希。
计划文件属于 Python 检查器产生的内部格式，SV 再检查范围、文件长度和模式；它不重新解析 ELF。

仿真传入 `+mode=PRELOAD +image_plan=/absolute/path/load.plan`。
`PROTOCOL_BOOT` 必须省略 `image_plan`，SV 会拒绝任何非空计划路径（包括空文件路径）。
Python 同样拒绝该模式带任何目标镜像。该模式保护整个外存窗口；片内 boot ROM 在 core 中单独装载，
UART/SD BFM 必须通过真实协议装载目标区。T04 只证明启动前目标区没有预加载，不证明下载或 CPU 启动成功。

## 检查与覆盖边界

`make_workload.py` 以字节字典生成独立参考；`check_axi.py` 对全部采样逐项检查请求、W 数据/strobe、
B/R 的数据/ID/顺序/计数/LAST、5 通道稳定性及并发深度，并从 VCD 在上升沿前重新采样与 CSV 比较。
读写并发使用不重叠地址；写后读在全部 B 完成后进行。模型同拍写提交早于生成读数据，
但不把同地址竞争的这一调度细节定义为系统同步方式。

矩阵覆盖 256/512MiB 两侧、窗口顶端、最高字节、低/高越界、32 位回卷、4KiB 页末/跨页、
最大 INCR、所有 WRAP 长度、窄 lane、零/部分 strobe、非对齐、重复 ID、未装载区、16MiB 稀疏 BSS。
另有复位后保留数据、排空、SLVERR/DECERR 注入恢复、非法镜像及损坏证据负例。
本卡是固定配置的定向＋种子回归，不是完整 AXI VIP、形式证明或全容量板端存储器测试。
