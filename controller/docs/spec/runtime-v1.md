# T12 RV32 运行时合同 v1

producer=T12；consumers=T18/T19/T20/T25。模型、数值与物理包保持 T05/T10/T11 身份。
实现入口为 `firmware/runtime/port/`，完整裸机入口为 `firmware/runtime/main.c`。

## 请求与停止

`nxr_begin_text` 接收已完整收齐的 UTF-8 消息，C 内执行模板、NFC、预分词、ByteLevel BPE；
`nxr_begin_ids` 为固定 token 测试及内部入口。`nxr_step` 每次执行一个真实模型 token，
`nxr_attach` 将同一个请求状态机接到 T11 C 数值图。外部调用者串行持有请求对象；同一对象
在执行回调中的重入会返回 BUSY，不提供多线程调度或请求队列。

| 项目 | 本版限制 |
|---|---|
| 原始消息/模板 | 最多 4096 UTF-8 bytes、32 条消息；system/user/assistant 文本 |
| 请求输入 | 1–512 token，包含完整聊天模板 |
| 总上下文 | 输入＋已生成 token ≤512 |
| 生成 | 最多 128；EOS=151645；相同 logits 取最小 ID |
| KV 物理分配 | 保留 T08/T10 的 640 槽，24 层 FP32，共 15,728,640 bytes |
| 状态 | IDLE → PREFILL → DECODE → STOPPED；接受后失败进入 FAILED |
| reset | 拒绝活动调用；成功后 session 加一、sequence 与 KV 有效长度清零 |

512 输入是合法请求，prefill 后以 `total_context` 停止，输出 0 token；511 输入至多输出 1。
EOS 也计入生成/总 token 数。达到 EOS 优先记录 EOS；否则先检查总上下文，再检查生成限额。
最后一个输出 token 无需再写入 KV；KV length 与输入＋输出的计数分别保存，不混为一谈。
物理 KV 缓冲可以复用，只有当前有效前缀可读。失败后输出不可发布，必须 reset 后重新 prefill。
`nxr_count`/`nxr_output` 仅在 STOPPED 发布结果。

T08/T11 的 512 输入＋128 输出、640 物理容量保持原合同；本版在其上收紧请求总上下文至 512，
满足 T12 任务卡，未缩减模型或改变数值。直接调用低层 `nx_forward` 的容量仍为 640；下游请求
必须经 `nxr_*` 执行限制，不能将低层参考 API 当作无界应用入口。

单请求 timeout 覆盖分词、prefill、decode，不随每个 token 重置。时基为主机单调 ns 或 RV32
mcycle 的高/低/高一致读取。同步内核返回时再次检查截止时间，超时结果丢弃；这是协作式
截止检查，未宣称具备异步抢占正在执行的内核的能力。硬件驱动自己的排空/恢复由 T13 接续。

## 原始 tokenizer 与格式

源文件必须匹配 `application-v2-model-lock.json` 中 `tokenizer_files`；不使用适配权重目录中
重新序列化的 tokenizer。`model_tools/export_tokenizer.py` 输出 little-endian `nxt-v1` 表，
保留完整 151,643 基础词表、22 个 added tokens、151,387 个 merge 的原始 rank。

Unicode L/N/空白分类直接从锁定 tokenizers 的 regex 引擎提取；NFD/NFC 分解/组合直接从
该 normalizer 提取。CCC 候选逐个与其实际重排行为核对，不假设 Python 自带 Unicode 版本相同。
运行时没有 JSON、正则、Python 或词典裁剪依赖。C 采用有界 scratch、检查过的偏移和二分查找。
文件/表内容的完整 SHA-256 由装载者验证，`nxt_init` 另校验版本、大小和各 section 范围。

聊天模板支持本项目实际使用的文本消息及默认 system 前缀，与官方 `apply_chat_template`
相同；tool-role/工具 schema/多模态消息明确拒绝，不能静默输出另一种模板。
special token 的 `special` 标志决定 decode 是否跳过；`<tool_call>` 等普通 added token 保留。
模型补齐词表的无词条 ID 151665–151935 解码为空，与官方一致；超出模型词表拒绝。
流式 decoder 跨 token 保存不完整 UTF-8 字节，仅发布完整字符，最终截断或错误字节以 U+FFFD
替换。输入非法 UTF-8 拒绝。输出容量不足时不改变调用者的 token/count/decoder 状态。

## 内存与 ABI

无推理堆分配；`nx_init_static` 绑定互不重叠的 state/KV/work 三块内存。
`nxr_arena` 检查物理分区、T10 实际预算上限、对齐、乘法/加法溢出，失败不推进 cursor。
`nxr_file_span` 使用 uint64，支持大于 4GiB 的文件偏移计算，但最终 RV32 地址必须单独检查。
size_t/uintptr_t 在 RV32 编译时静态断言为 32 位；模型包文件偏移从不直接转成指针。

| 对象 | 完整固件位置/字节数 |
|---|---|
| 权重、scale、小参数 | T10 region_offset＋0x80000000；embedding/head 共享 |
| KV | 0xA8000000；15,728,640 bytes |
| 图内部 workspace | 0xAC000000；664,576 bytes；M=1 |
| 请求最后位置 logits | 0xAC0A2400；607,744 bytes，不与内部原子发布缓冲重叠 |
| 程序、rodata、data、BSS | 0xB4000000 起，链接断言 ≤8MiB |
| 有界 heap 预留 | 0xB4800000 起 ≤8MiB；完整当前固件实际 heap 使用 0 |
| 栈 | 0xB7FF0000–0xB7FFFFFF；64KiB，最低 16 bytes 保护区 |
| 原始 tokenizer 文件预留 | 0xB8000000；11,488,512 bytes |
| 编译索引 | 0xB8AF4D00；5,079,627 bytes，低于 T10 5,630,976 限额 |
| tokenizer scratch | CPU 私有 BSS，212,992 bytes；没有写入只读 tokenizer 分区 |
| 请求交换区 | 0xBA000000 起；CPU/NPU 可写数据不与程序、栈、tokenizer 重叠 |

ILP32、RV32IM 软件浮点；不链接 OpenMP/POSIX 时钟。超越函数沿用 T11 的 double 计算后立即
舍入 FP32，其他计算仍是 FP32。RV32 使用锁定 newlib 内的 IEEE sqrt/exp 内核，避开 POSIX
数学错误包装层。实际调用保留显式数值错误检查。64KiB 栈以 ELF `.su` 和真实执行 sentinel
峰值共同检查；主机 RSS 只反映测试进程，不冒充 RV32 工作集或实物容量。

## 后端接入

当前安装并执行的实现是 CPU_C。`nx_bind_backend` 提供同步 linear 回调与逐调用 trace；
shape、矩阵 view 和输出视图保持相同，合法但不支持的调用须在修改结果前返回
`NX_UNSUPPORTED` 才可回退同一个 C kernel。其他失败使会话失效，不自动换 CPU 隐藏错误。
trace 记录实际 route、fallback_reason、status、ticks；`nx_profile` 保留各 CPU 算子调用数/时间。
固定 CPU 的 attention/vector 计时同样保留。硬件回调未安装时不会声称执行过 Coral。

这是 T12 数值图到后端的源码适配点；T08 的物理 tensor/context API 与实际 Coral 驱动、所有权、
提交/完成协议仍由 T13–T16 实现并验收。本卡的 unsupported/fault 回调是显式调度测试夹具，
不作为任何硬件执行或 T08 tensor 地址校验器已实现的证据。

## 完整基线及交接

```sh
make t12
make t12-smoke
make t12-test
npu-python scripts/run_cocotb.py --task T12 --suite regression
make t12-full-cpu ARGS='--text 打开客厅灯。 --max-new 128'
npu-python software/runtime/run_cpu.py --verify-full
```

完整 CPU 路径固定同一个 T10 包，用 C 分词、C 请求状态机、完整 24 层 C 数值图和完整词表。
host 仅映射已校验只读权重并提供 arena/时钟/控制台。`make t12` 同时生成完整 RV32 ELF，
`firmware/full/full-model-identity.json` 记录地址/包身份。裸机示例交换区布局为五个 little-endian
u32：`0x3152514E`、UTF-8 长度、max_new、timeout_ticks 低32、高32，随后是 UTF-8 文本。
T18 负责协议装载和包真实性校验；该 PRELOAD 入口不代表 SD/UART 协议启动已完成。

验收矩阵同时包含真实 CPU 控制/分词、T11 冻结线性 tile、完整宽度 RMSNorm、量化舍入边界，
及同源 1 层 hidden=64/intermediate=64/vocab=64 的连续 token 数值用例。小模型只验移植，
完整模型数值/质量仍绑定 T11，T25 才验收完整模型板端推理。T12 不要求 PDS、DDR IP 或实板。
T04 内存模型作为两个 AXI responder 共用同一 backing store，cocotb 从被动 AXI 观察值独立比较；
CPU 源码不包含预期输出。保留启动 10,000 周期代表波形、逐次 XML/检查数/输入身份、随机 seed
及同 seed 复跑，空测试/坏 golden/缺 XML/CPU 保持复位必须失败并保留原始 FAIL。
