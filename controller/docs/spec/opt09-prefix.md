# OPT09 固定前缀合同 v1

候选覆盖层为 `variants/opt09`，叠加已验收的 OPT08；运行时和流式代码继承 OPT06。`NX_PREFIX_ABI=1`。只增加进程内接口，所有消费者重新编译；模型包、CE 描述符、FP32 KV 和 T12 总上下文 512 保持原合同。

`nx_prefix_identity` 逐字节绑定模型包、tokenizer、模板、数值配置和后端配置的五个 SHA256，以及 ABI、前缀绝对起点、上下文限制、flags。另保存最多 512 个完整 int32 token IDs，匹配时比较长度和所有 IDs。身份不以文本前缀或短哈希替代。各摘要必须非零；生产者负责从已 seal 的实际对象构造摘要，在模型重装、近似开关、后端/布局变更前调用 configure/rebind/reset。外部不得改写 session 的私有 KV 或量化 scratch。

当前缓存从绝对位置 0 开始。其他起点在 prepare 时拒绝，在 restore 时算作未命中；普通请求从位置 0 完整 prefill。支持非零起点需要显式交接更早的所有层 KV，本接口不猜测缺失状态。模板后的完整 token 前缀取自 OPT05 冻结输入，测试实际使用其中 24 IDs。

`nx_prefix_prepare(session,key,ids,n)` 先撤销旧状态，逐 token 执行原图，跳过不需要的 head。成功后各层 K/V 的 `[0,n)` 有效，记录精确 IDs 和身份。准备失败、零长度、超过 512、非法 ID 都不会保留可命中的旧记录。单独计准备时间。该函数只保存身份和 IDs，不分配或复制另一份 KV，也不保存完整词表 logits。

`nx_prefix_restore(session,key,ids,n)` 仅在身份/IDs/长度全部一致、session 成功有效且原前缀仍保留时返回 1。它撤销输入量化借用和 logits view，将逻辑有效长度恢复为 n；原 KV 存储地址和前缀区域不变。旧后缀的物理字节可以留在内存，但有效区不包含这些字节；attention 只按新的 past 遍历，下一步覆盖当前位置。未命中返回 0，并使 session 回到空长度，调用方完整 prefill。`NX_OPT09_PREFIX=0` 强制走该冷路径。

`nx_cache_view` 同时返回只读地址和有效 token 数；调用方只能读取这个跨度，每 token 为原 KV 宽度。下一次 forward/restore/reset/error 后必须重新取 view。旧 `nx_cache` 是兼容原始诊断接口，仍须配合 `nx_length`，不能把底层容量当有效长度。`nx_logits_v2` 只在当前请求的完整 head 成功后有效；prepare、restore、无 head 的 forward、reset 和错误都撤销 view。

reset 明确丢弃前缀。`nx_bind_backend` 即使绑定相同地址，也视为一次后端会话变化并 reset。configure 的身份变化也 reset。forward 的参数、位置、数值或后端失败撤销 session 和命中资格；失败后必须重建，不能在原 prefix_ready 上恢复。

运行时适配层提供 `nxp_init/prepare/begin`。它必须与 `nxr_request` 的模型回调绑定同一个 session，遵循现有同步、单所有者调用合同。`nxp_begin` 经 `nxr_restart_ids` 清空上次的输出、采样时间、停止原因、错误和长度，增加 request session 身份，然后将已验证的 prefix 长度同时设为 prefilled 和 kv_length。请求仍从 PREFILL 开始，OPT06 的 `nxs_open/update/finish/abort` 可直接使用。active/busy 时返回 BUSY，不执行 restore。

没有后缀的请求采取完整冷算，以保持最后一个 prompt head 的原语义；零前缀按普通冷请求处理。prompt 长度、最大输出、token IDs 和 timeout 在改变缓存前校验。输入加生成的总数继续由 T12 的逐步 512 上限控制。过长/非法请求被拒绝后不改变先前的成功缓存，因为没有执行模型；已开始请求的 timeout、回调失败和流式 abort 则立即调用 model reset，撤销所有前缀和最终发布资格。重建成功后才能再次命中。

费用分别报告准备、原始 restore、冷请求 TTFT/总时间、热请求 TTFT/总时间。首次“先准备再请求”的费用为准备加第一次请求，不能只报告热请求时间。RV32 小图实测只代表该图和 T04 行为 AXI；完整 0.5B 的逐位数值验收与主机验证耗时独立记录，不据此生成板端 TTFT/token/s 预测。OPT13 接收 past/有效区与接口；OPT16 负责最终生产入口及其他候选集成，OPT17 才执行实板测量。
