# K/V 尾段、长 PV、输出流 argmax 候选

这三项均已接入现有生产调用链，默认关闭。它们是需要板上复测的候选，不是新的硬件资格声明。公开 `CE64_CAPS` 仍为 0。测试采用真实 C/RTL 运算与显式标注的外部设备模型，不把仿真周期当作完整模型或实板性能。

## v4：修复短 PV 的 4 KiB DMA 分段

v3 的 `chunk` 只有 `long_pv` 时受页尾约束，遗漏了默认短路径。生产 M4 attention 的第二 KV group 输出 `0xAC00AF00`，即使 length=1，原首笔 512 B 命令也会跨过 `0xAC00B000`，由原 CE DMA 拒绝。

v4 对所有 P 读和 Y 写使用 `min(剩余字节, 512, 当前页剩余字节)`。同时保留短 V 原有 16 B 对齐契约，把可能跨页的 256 B 行读取拆成页内片段，scratch 地址随行内偏移前进；整行成功完成后才换行。长 V 的 64 B tile 和既有浮点运算次序保持不变。修复对默认 `LONG_PV=0` 和增强 `LONG_PV=1` 都有效，没有新增修复开关。

控制器完整矩阵与命令见 `README_PV_BOUNDARIES.md`。针对性复现入口为 `run_pv_boundaries.py`（PV 控制器、实际 FP、行为 DMA）及 `run_ce_production_page.py`（实际 CE、descriptor、DMA 和 MMIO P-window）。后者使用报告中的两组 Y 地址与 local P-window，让每组 DDR 读取保持 256 B，直接观察实际 AXI 接受的写入与全部 896 个输出 word；详细命令与范围见 `PV_PRODUCTION_PAGE.md`。可使用同一新夹具的 `--rtl-source` 指向保存的 v3 源码，记录旧版负例。

合成有限 FP32 输入不等于原板完整 W 的真实模型 golden。本修复也没有闭合报告中的普通文字首 Q 故障或 v3 已记录的通用 FP 输出背压问题。当前正负例均保留实际源码身份和既有 FP 仿真表示限制，见包根 `verification/v4/`。

## 开关与兼容

| 功能 | 固件宏，默认 0 | CE / SoC RTL 参数，默认 0 | 硬件探测 |
|---|---|---|---|
| K/V 未发布尾段直接输出 | `NX_KV_TAIL_DIRECT` | 无新增要求 | 使用原有 opcode 2 和原有 A8 输出地址能力；新增的是软件精确 lease |
| PV 长度至 512 | `NX_PV_LONG` | `LONG_PV` | MMIO `0x130 == 0x50563531` |
| 完整词表 finite/argmax | `NX_HEAD_ARGMAX` | `HEAD_ARGMAX` | MMIO `0x134 == 0x414d5831` |

增强构建显式传入所需宏和参数。旧 bitstream 没有长 PV/argmax magic 时，在接受新操作或消费 token 之前返回 unsupported，由原参考路径完成。同一调用一旦已经提交或出现错误，不隐藏失败，不重试另一执行器。短 PV 的原 2 KiB P-window、原 ≤64 路径保持可用。

## 1. 精确 K/V 尾段 lease

`nx_reference` 在执行当前层 K 或 V 线性变换时，临时生成 `nx_kv_tail`，授权范围恰好为 `[past, past + rows)`。其身份包含 owner、单调不回绕 serial、K/V 选择、layer、past、rows、arena、destination 及模型几何。调用前后均重新验证。复位、前缀失效、重新绑定和返回都会撤销活跃 lease。

`nxr_ce64_linear_kv` 额外检查生产几何 24 层、640 容量、128 宽度和精确 A8 arena 大小，核对当前层矩阵的不可变 q/scale/bias 视图，以及所有输入、输出、暂存区的 bounds/alias。它没有把整个 A8 加入 private-workspace 白名单。原线性提交、epoch/session/sequence、超时、完成、DDR drain、ACK 和 fence 检查继续执行。

成功后省去的 memcpy payload 为：

`24 layers × 2 tensors × 128 values × 4 bytes = 24,576 bytes / token`。

按一次 memcpy 读写各一次计算，可避免的 CPU 字节访问量为 49,152 bytes/token；这只是代码路径的计数，不是独立 AXI 总线测量。`kv_output_saved_bytes` 统计 payload，不应再误称为双倍 DDR 带宽节省。失败可能污染尚未发布的尾段；模型会失效，请求不会获得 token 或有效视图。旧已发布前缀的地址不在 lease 内。

## 2. 长 PV 的存储与数值顺序

实际 `nx_pv_control` 根据 `LONG_PV` 选择 `MAX_LENGTH=64/512`。长度大于 64 时采用以下 64 KiB scratch 布局：

| 区间起始 | 内容 | 最大占用 |
|---|---|---:|
| `0x0000` | heads × padded 个 FP32 P，padded 为 2 的幂 | 14,336 B |
| `0x4000` | 16 个 V 维度 × length 的一块 | 32,768 B |
| `0xc000` | 一个输出维度的完整 padded 产品/归约树 | 2,048 B |
| `0xf000` | heads × 64 个 FP32 Y | 1,792 B |

四块 V 分别覆盖维度 0–15、16–31、32–47、48–63。每个需要的 V 元素只读一次。每个输出先生成全部单独舍入的乘积、补零，再按原相邻配对树逐层相加。没有先对小块求和再组合，没有 FMA 合并，也没有更改 FP32 舍入实现。

长 P 使用原 BA 输入暂存区和 `heads × padded` pitch，不把长 P 塞进短 P-window。长路径要求 P 512 字节对齐、V 256 字节对齐；硬件与驱动均验证这些条件。Y 保留 16 字节对齐的原契约，DMA chunk 在 4 KiB 边界分段。完整 512×7 调用的输入 payload 是 `7×512×4 + 512×256 = 145,408 B`，输出 1,792 B。调用者仍保有对旧 bitstream 的 CPU fallback。

## 3. 被动 finite/argmax 观察器

`nx_ce64_head_argmax` 接在实际 CE DDR 输出 AW/W handshake 上。仅 opcode 2、M=1、N=151936 的候选 head 激活。它检查词表输出按序且完整覆盖，检查 strobe 和 WLAST，对每个 FP32 指数检查 finite。比较采用严格 `>`，相等保持先出现的 index；正零与负零相等。任一 NaN 或 ±Inf 都使结果失败。

观察器不改变 DMA 数据、调度或完成顺序。它在全部 151,936 个值到达、AW/W 已完成、原成功 completion 到达且 epoch/session/sequence/descriptor-generation/commit-generation 都匹配后才发布。软复位、故障、隔离、模型窗口撤销和下一次 submit 会撤销结果；正常完成后的 CE→CPU 所有权交接不会误撤销 CPU 即将读取的结果。

结果位于 MMIO `0x140..0x16c`：status、index、best FP32、count、epoch、generation、session low/high、sequence low/high、destination、vocab。软件把这份结果绑定到刚完成的模型 head，再读 generation 检查一致性，并把 token 先放入临时变量，全部校验通过才发布。结果一次消费。缺 capability 才走原 `nx_greedy`。

完整 logits 的原 DDR 输出、完成检查和可读诊断视图均保留。正常生成可以避免 CPU 再扫描 `151936×4 = 607,744 B`；`head_read_saved_bytes` 是避免扫描的 payload 计数，不是完整系统的测速结果。

## 回归范围

### 原生 C

```sh
python3 -m unittest tests.competition_memory.test_native -v
```

- 真实两层精简模型，M1/M4、132 个位置，逐位比较 logits 和 K/V；baseline 宏为 0、增强宏为 1 各执行一次。
- 活跃 tail 逐字段损坏、返回后重用、尾段部分写后失败、回调中重置，以及 head 失败不发布 token。
- 真实 `ce64_backend.c` 和真实 tensor validator，使用明确的 completed-transport stub，覆盖生产层 0/23、K/V、rows 1–4 和接近 512 的尾段。8 类错误注入包括 rc、output-valid、epoch、session、sequence、超时、状态和 lease 撤销。
- 真实 `opt12.c`，验证所有长度边界、旧 capability、未初始化 context、空 read32、sequence、地址和对齐错误、提交失败及超时后失效。

父集成树另外增加了 prefix capture/restore 与整数 profile 的联合门；这里的独立树不替代该门。

### RTL 重建

```sh
python3 tests/competition_memory/run_rtl.py \
  --verilator /path/to/verilator \
  --verilator-root /path/to/share/verilator \
  --out /tmp/t27-memory-rtl --split-fp-registers
```

默认执行 PV、完整词表 argmax、完整 CE、关闭新参数的 CE capability 检查。每项写入完整 build command、工具版本、源码 SHA-256、结果、stderr 和 receipt。也可用 `--only pv|argmax|ce|ce-baseline|metadata` 单独执行。

PV 覆盖 1、3、63、64、65、127、128、129、255、256、257、511、512，含 512×7 全部 448 个输出和 Y 起始页偏移 4080 的跨页调用。使用原实际 FP RTL，对独立、分别舍入的 host FP32 adjacent-tree 结果逐位核对。随机 DMA 停顿、3 个读错误、timeout、stop、非法 513 也执行；失败不写 Y，非法 shape 不发 DMA。

完整词表 argmax 执行 22 场实际 RTL：正常、两个方向的 ±0 最早 tie、重复最大值、subnormal、late NaN、signaling NaN、±Inf、漏写、部分 strobe、错误 WLAST、额外 AW、重复写、错误 epoch/session/sequence/generation 和完成失败。含 128-bit burst 及 32-bit 窄写，后者 AW/W 同周期接受。

完整 CE 包括实际寄存器、descriptor validator、dispatcher、DMA、scratch、dot 和 FP 管线。MMIO master 与外部 DDR slave 是行为模型；外部 guard/DDR adapter 没有实例化，其状态输入固定为 idle、drained、无故障，因此本门不覆盖 SoC guard、仲裁和 DDR adapter。本地实际 DMA 仍必须收到 R/B 响应后完成，testbench 也独立检查读队列为空、全部写响应已退休才接受 completion。M1/M4 的 K/V 直接 A8 输出与原 BA 暂存输出、独立 FP32 结果逐位一致，并检查 tail 前后地址保留。另执行 65×7 长 PV，Y 跨 4 KiB，全部 448 个值和实际读写 payload 一致。这里没有执行完整 0.5B 模型 head；151,936 个 logits 的选择器验证是上述实际模块的完整输出流测试。

## 仿真兼容与明确未通过的门

Verilator 5.006 对原 retimed FP packed array 同时具有连续 element-0 和其他 element 的 FF 驱动不接受；仅豁免 `BLKANDNBLK` 后，完整 CE 出现 FP 输出 epoch=0，原 epoch guard 正确返回 -9。此 raw 完整 CE 门没有通过。

当前源码的原 packed 表示，单独 MUL、固定 ready 的 1,024 个 metadata 样本也通过。因此不能把完整 CE 的负例泛化为所有原 FP 管线都丢失 tag，也不能把其根因断言为一种已彻底定位的工具错误。证据目录分别保留原表示 standalone 正例、早期 raw CE 负例和当前源的完整 CE 兼容表示正例。

`--split-fp-registers` 只在输出目录生成仿真副本：在原 16 个 generate block 中，把每个 FF 输出拆成与原 element 完全相同类型的局部 register，再通过连续连接接回原 array index。所有 FF 宏、reset、enable、RHS、运算、下标和延迟不变，生产 FP 源码不变。该模式不豁免 `BLKANDNBLK`。原源码、副本、unified patch 及各自 SHA 都保留。转换脚本拒绝不匹配的结构。

独立 FP metadata 测试的固定 ready 模式通过 1,024 个真实乘法、251 种 epoch、1,024 种 sequence 和 77-bit aux，并跨输入暂停传播：

```sh
python3 tests/competition_memory/run_rtl.py \
  --verilator /path/to/verilator --verilator-root /path/to/share/verilator \
  --out /tmp/t27-fp-fixed --only metadata \
  --split-fp-registers --metadata-fixed-ready
```

**广义输出 backpressure 的独立 FP 门仍失败：样本 2 收到前一项的 tag/value。** 省略 `--metadata-fixed-ready` 可以复现该负例。单独 unpack metadata 和完整的等价分元素表示都没有消除它。本轮没有修旧 FP 控制或更改数值运算，也没有通过取消 epoch 检查掩盖失败。当前证据不能把它确定为实板缺陷或单纯仿真兼容问题；需要合格 HDL 仿真环境复核。完整 CE 的通过只覆盖这里的实际消费者模式和随机 DDR 停顿，不外推为通用 FP backpressure 证明。

未完成的外部资格包括生产模型完整推理、真实板 DDR/CPU 性能、时序/面积/PDS 和泛化 FP 背压门。因此三个开关保持默认 0，不能用这些测试结果替代比赛板上速度、正确性和资源报告。
