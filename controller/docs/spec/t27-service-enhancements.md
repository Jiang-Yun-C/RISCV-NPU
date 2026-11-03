# T27 可选运行服务增强

固定系统前缀复用、整数周期计时、会话取消、请求期限和硬件快照已经接入生产
`firmware/runtime/board/main.c`。默认构建仍沿用 baseline；增强必须显式选择。
本说明验证代码与协议行为，不把合成模型、主机耗时或软件估算当作实板收益。

## 构建与执行身份

```bash
python scripts/build_t27_streaming.py \
  --generated /path/to/real/production-assets \
  --output /path/to/new/application-build \
  --service-enhancements --build
```

`--all-enhancements` 同时选择服务增强、`--kv-tail-direct`、`--pv-long` 和
`--head-argmax`。后三项也可以分别选择。`--profile optimized` 单独选择保留数值合同
的 `-O3`；所有 feature 默认关闭，默认 profile 仍为 baseline。固件开关不产生对应
硬件功能；硬件路径仍需匹配位流与 capability，旧位流按后端规则回退。

构建工具生成 `t27_runtime_identity.h`，绑定实际 tokenizer/template、reference /
port、有效编译参数、编译器 SHA256、driver / RTL / board / t27 CPU 源码和 M4 配置。
模型与 tokenizer SHA256 继续来自生产资产头。继承 receipt 若已含工具管理的 feature
定义或取消定义，会拒绝构建，防止后一条宏覆盖显式选择。缺真实资产时不会使用测试
fixture 生成生产 ELF。构建身份用于防止进程内错误复用 KV，不证明板卡实际烧录了哪个
位流；正式 A/B 仍需真实固件、位流、时钟、模型与 tokenizer 部署记录。

## 固定前缀进入真实请求

服务先对完整聊天模板分词，再与当前 tokenizer 对固定 system 模板得到的 token
序列逐个比较。只有完整请求确实以同一序列开头、并且仍有后缀时才选择复用；否则走
完整冷路径。没有字符串近似匹配、短哈希、缓存 logits 或固定答复。

第一条冷请求正常计算前缀。M4 分块在封存位置收短，不跨过前缀边界。该边界完成后，
`nx_prefix_capture()` 检查真正由 forward 观察到的 IDs、逻辑 KV 长度、模型状态和
完整身份，封存已有 KV。没有额外预热一遍再隐藏准备成本。命中请求仅恢复前缀逻辑
长度，继续计算后缀与新 token。

每次请求仍执行加速后端 epoch/drain/reset，撤销上一请求的传输或借用状态；有效模型
前缀 KV 保留在独立模型状态中。新 session 的时钟、输出、停止状态和计数重新开始。
`:reset`、失败、取消、身份变化、前缀不匹配和关闭复用使旧前缀失效。

| `T25 PREFIX 1` 字段 | 含义 |
| --- | --- |
| `session` | 本条请求的完整会话身份 |
| `hit` | 是否实际恢复已封存前缀 |
| `captured` | 本条冷请求是否封存前缀 |
| `tokens` | 本次实际匹配的前缀长度 |
| `prepare_ticks` | 封存前实际计算前缀的时间，已包含在该请求 `prefill_ticks` 中 |
| `restore_ticks` | 恢复检查与逻辑长度恢复的时间，不是前缀重新计算时间 |

冷 / 热请求分别记录，`prepare_ticks` 不可再加到 prefill 上，也不可把首次准备移出
总成本。生产 main 缩小合成图比较输出、logits 和完整有效 KV 摘要，验证冷路径、命中
路径和关闭复用路径相同；该测试不代替真实全模型质量或板端性能测量。

## 三种不同计时口径

1. `METRICS` 保留请求控制器计时。`tokenizer_ticks`、`prefill_ticks` 和
   `decode_ticks` 分别记录；用户可见首字符仍从真实接收 chunk 计算。
2. `PROFILE 1 REQUEST / PREFILL / DECODE / CUMULATIVE` 是八类被标记算子的计时
   与调用数。板端选择 `NX_PROFILE_INTEGER=1` 后，热点累加直接使用 `uint64_t`
   周期，导出兼容接口时才转换。主机秒 API 保留。REQUEST 与两阶段逐项差分严格相等；
   CUMULATIVE 为启动以来累计。算子时间包含内部驱动和等待，排除外层 UART、分词和
   控制开销，不要求八项相加等于完整请求时间。
3. `PMU 1` 是硬件冻结快照窗口。START 在本条分词、prefix restore 和 REQUEST
   声明输出之后、流式 BEGIN 之前；PREFILL 快照在最后一个 prompt block 完成之后；
   STOP 在计算循环结束后、栈检查及最终发布之前。REQUEST PMU 包含窗口内串口、
   轮询和观测开销。Decode 差分包含首 token 发布等发生在预填充快照之后的工作，
   不能解释成纯 decode kernel 时间，也不能与算子 profile 直接相加。

PMU 使用全64位软件 session、32位硬件 tag 和不回绕的 sequence 共同校验。软件
session 超过 `UINT32_MAX` 时停用短 tag，不截断复用旧 tag。硬件同时满足 capability
magic、snapshot magic 和 ABI1 才可用；旧位流输出 `available=0 valid=0`，不生成零值
冒充实测。overflow、协议错误、tag/序号不一致使记录无效。有效 REQUEST 等于 PREFILL
加 DECODE 的每项计数；解析器拒绝缺项、重复、错 session 和差分不一致。

硬件 PMU 的 AXI 字节与 `TRANSFER 1` 软件搬运计数分别呈现。后者表示统计到或避免的
软件 copy/scan 字节，不等于实际 DDR 流量：

| TRANSFER 字段 | 范围 |
| --- | --- |
| `input_staged_bytes` / `input_saved_bytes` | 实际输入 staging 与避免的 staging |
| `output_copy_bytes` | 实际输出回拷 |
| `output_saved_bytes` | 私有工作缓冲路径避免的输出回拷 |
| `kv_output_saved_bytes` | KV 尾部直接写入避免的回拷 |
| `head_read_saved_bytes` | head argmax 避免的 CPU logits 扫描读取 |
| `input_staging_ticks` / `output_copy_ticks` | 软件搬运的整数周期计时 |
| `backend_cycles` / `completed_calls` | 已完成后端调用的累计值在请求前后取差分 |

三个“避免的字节”字段独立，尤其不会把 head 读取合入输出回拷。

## 会话取消与期限

板端先发 `T25 REQUEST 1 session=<16 位十六进制> ...`。UI 取得身份后才允许发送一次
`:cancel <同一 session>`。串口桥接的单请求约束只允许这个精确绑定的命令插入当前
请求；迟到身份返回 stale，不影响新的请求。UTF-8 正文仍由流式和长度帧协议处理，
正文里的控制文本不会成为真实控制响应。

这是协作取消。UART 只在完整 block/token 边界轮询；当前 forward、CE 调用及其超时
决定响应延迟，不会在 DMA 写到一半时硬中断。`nxr_cancel()` 在 busy 时仍返回 busy。
取消或失败后先撤销 prefix、完成 driver drain/reset，再进入 READY；恢复失败进入
NOT_READY，只接受 reset/reload 恢复。断开串口或关闭页面本身不会取消板端计算。

`:timeout <1..86400>` 以秒显式配置后续请求期限，默认保留原86400秒保守值，避免
缺少实板证据时将正常长推理误判超时。声明记录实际 timeout_ticks，UI 提供调整。
`:prefix 0|1` 用于冷热 A/B；`:identity` 是只读模型/tokenizer 查询，不撤销前缀。

## 自动整轮采集

`software/competition_semantics/collect.py` 使用现有 SerialBridge 和同一 T25Parser。
它消费冻结24例 plan，依序发送真实 prompt，每次完成或失败立即保存独立 export、
原始接收 chunk journal 和 manifest，再发下一条。不依赖 UI 的20条历史缓存。

默认只输出计划；`--capture --port ...` 才打开选定 CP2102。采集要求支持有上限的
`:text` 和只读 `:identity`；身份查询等到自身应答后才继续，避免启动/空行同步的
额外 READY 被误认成请求完成。实际收到的身份经核对后保存原文，不把预期 SHA 写成
观测到的 SHA。部署身份仍不是独立硬件证明。

每条 chunk 保留原始 base64、连续序号和 Python monotonic_ns 时间，接收批次 fsync
journal；完整请求经同一 export adapter 重解析才标记 completed。部分 UTF-8、缺
READY、错 session、丢 chunk、协议失败和断线不计成功。失败与未尝试条目仍在固定24例
分母里；已开始 plan 拒绝覆盖或静默重试。

主机默认等待86460秒，容纳原24小时板端期限及串口尾部。这个上限不修改板端期限；
先触发时保存部分记录并停止后续请求，明确记录断开不代表取消。较短板端请求期限
应通过服务 timeout 配置，不能把主机等待上限冒充板端取消。

## 验证范围

生产 main native 缩小合成图覆盖前缀冷热同值、suffix 变化、复位/禁用失效、capture
拒绝错 IDs/错身份/失败 forward、取消恢复、迟到取消、超过 double 精确整数范围的
绝对时钟、期限边界和真实 wire 分片。取消解码测试用超过 `2^53` 的完整64位身份，
检查 LF 生效、非法字节、UTF-8 噪声、溢出及下一条恢复。

JS 回归覆盖旧记录、UTF-8、长度帧、阶段/PMU/搬运字段、前缀记录与错误拒绝；bridge
回归覆盖 owner、单请求、会话取消和正文里的假 READY。批采集以显式 fake serial
验证24条保存、错误停止、断线部分保存与固定分母，fixture 模型准确率始终为 null。

本环境未执行新的真实板端请求，也没有可用 Chromium 完成新增控件视觉检查。保留的
`service_enhancements_smoke.mjs` 需要 Playwright 浏览器和明确合成来源的 native wire，
不属于已通过证据。生产 RV32 / 全 feature 组合编译及集成由合并后的验证记录提供。
