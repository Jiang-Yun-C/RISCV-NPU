# OPT06 流式输出与计时合同 v1

本接口在隔离 B 工程上应用 `variants/opt06/` 覆盖层；所有 `nxr_request` 消费者必须重编译。根工程原有 A 固件与 OPT01–05 历史身份保留。`make opt06` 建立新的 B+覆盖层候选和证据目录。

## 请求与发布

服务声明 `T25 SERVICE v2`，每次 READY 前声明 `T25 CAPABILITIES stream=1 text_max=1`。新客户端只有收到能力声明才把文本请求编码为 `:text MAX_NEW TEXT`，上限为 1–128；旧服务继续接收原始单行文字。`:ids`、`:verify`、EOS、512 总上下文、`T25 STEP/IDS/TEXT/METRICS` 保持兼容。`:stream 0` 关闭预览；`:stream 1` 开启预览。此开关不改变模型调用、IDs、停止原因或最终完整解码。

`nxs_open/update/finish/abort` 是同步、不可重入的预览接口；每个新生成 ID 只送给已有 `nxt_decode` 一次，结束时 flush 一次，不重解历史。decoder 只提交完整 UTF-8 标量，空/special/padded token 不发布空 TEXT。最终 buffer 和 decoder 均有容量检查。失败丢弃 pending bytes 和最终结果；必须 reset 才能再次请求。调用方不得在活动流上直接 open，必须先 finish/abort；reset/reload 同样先结束活动预览。

`nxr_output` 仍只在 STOPPED 有效。预览读 `request.output` 仅限此专用适配器，没有执行器或语义提交权限。最终成功还需栈等调用方检查通过；失败、超时、ABORT 或断连都不能把预览保存为成功动作。

## 线路格式

每条事件是 ASCII 单行，以 LF 结束；数值为固定 16 位小写十六进制。

```text
T25 STREAM 1 KIND session=... sequence=... index=... ticks=... token=... error=... data=...
```

KIND 为 BEGIN、TOKEN、TEXT、END、ABORT。身份为 `(session,sequence)`；BEGIN 的 index=0，TOKEN 的 index 从 1 连续递增，TEXT/END/ABORT 对应已消费 token 数。TEXT 的 data 是一个或多个完整 UTF-8 标量的逐字节 hex；其他事件 data 为 `-`。结束 flush 可在同一 index 发布 TEXT，token 为 `ffffffff`。TOKEN 是观测事件；相邻 token 的准确采样点由 TIME 的 tokens 提供，不能拿打印事件时间替代。

最终兼容 `T25 TEXT` 前增加 `T25 TEXTLEN 1 bytes=... `。新客户端按该 UTF-8 字节数收齐原文，文字中的换行、CR、READY/METRICS 字样不作为控制事件。拼接的预览必须与最终完整文本一致，预览 IDs 必须匹配最终 IDs。END 只结束预览；成功结果仍需 METRICS 和最终 READY。无新帧的旧记录沿用旧解析方式。

## 计时边界与开销

`T25 TIME 1` 中所有相对计时均从完整输入收到后立即读取的 `received_at` 起算。采用同一 mcycle 时钟；模型已装载，输入接收前的传输、上电装载、主机渲染调度不在这个区间。

| 字段 | 边界 |
|---|---|
| tokenized | template/tokenizer 或 IDs 校验和 begin 完成；含请求前 reset/setup |
| prefill | 最后一个 prompt forward 完成；包含最终 head/greedy |
| first_token / tokens | runtime 接受每个生成 ID 时、任何预览/STEP 打印之前 |
| first_text / last_text | 完整可读 TEXT 帧最后一个 UART stop bit 已排出后；关闭预览时为最终兼容 TEXT 排出 |
| complete | END、最终 IDs/TEXTLEN/TEXT 排出后；尚未打印 TIME/METRICS/PROFILE |
| decoder | decoder 调用周期累计，包含其有限缓冲写入 |
| callback | 同步预览回调累计，包含格式化、MMIO 和 UART drain |
| legacy | STEP/诊断/最终兼容输出周期累计 |
| wire_bytes / output_bytes | 预览帧字节 / 截至 complete 的全部输出字节；TIME 自身不计入 |

`ffffffffffffffff` 表示 null，空文本没有首可读时间；无生成 token 没有内部首 token。tokens 是每个生成 ID 的相对 mcycle 样本，以逗号连接；无 token 为 `-`。仅 G≥2 计算相邻 token 间隔，单 token/EOS 空文本不伪造吞吐或可见 TTFT。相邻 token 间隔包含其间的解码、预览、STEP 和控制开销；forward 的 decode_ticks 只描述其旧范围。

decoder、callback、legacy 串行且不重复相加；完整区间的剩余部分还包括模型、reset、输入处理与包装。TIME/METRICS/PROFILE 的遥测传输在 complete 之后，单独列明，不把这部分当成零成本。最终停止到下一次 READY 的尾部成本可由完整串口 trace 另行计算。旧日志的内部首 token 和 total_ticks 不等于可见 TTFT，`scripts/analyze_t25_stream.py` 对旧记录将 visible 留为 null。

## 仿真范围

独立 runner 为 `scripts/run_opt06.py`，资格入口为 `make opt06`，使用真实 hard-float VexRiscv、真实运行时/tokenizer 和 UART RTL、T04 行为外存、cocotb 与独立原 tokenizer truth。完整故障矩阵的 UART divisor=16 用于缩短仿真；额外 divisor=250 的 split/legacy 对照按 125 MHz 归一化到 500000 baud，提供输出成本。测试台时钟为 10 ns，归一化只解释 mcycle；主机墙钟和该控制 fixture 的 forward 均不能作为完整模型速度。被动 SV 引脚采样、UART MMIO 写入、VCD 独立解码必须三者逐字节一致。

完整模型生成质量、实际 CE64 推理计时、长上下文算子数值、PDS/物理 DDR 和实板可见 TTFT 仍由下游卡验收。本卡只证明流式交互与软件计时，不能解除 OPT16/17 上板门禁。
