# OPT08 输入版本和缓冲合同 v2

OPT08 是 OPT05 冻结 B 的独立覆盖层 `variants/opt08`。`NX_INPUT_VIEW_ABI=2` 和 `NX_LINEAR_BINDING_ABI=2` 显式标记新的进程内接口；CE64 描述符、API-v2 线协议、group64 数值格式及 T12 原请求缓冲布局保持原版本。所有引用新结构的消费者必须重新编译，不能混用旧对象文件。

`nx_bind_input_observer` 在同步线性调用前传递 `(context, address, rows, K, version)`。版本零关闭复用。session 持有的非零 64 位版本只递增；每个新 norm1、attention 输出、norm2、SwiGLU 原地结果和 final norm 分配新版本。溢出使会话失效。Q/K/V 共享 norm1 的版本，gate/up 共享 norm2 的版本；新层、原地写、shape/地址变化和新 forward 必须换版本。reset、任何执行错误及 forward 结束调用空 observer，撤销全部借用。reset 不重置版本计数。输入及 Aq/Sa 在一个同步借用内只读，不允许别的调用、DMA 或 CPU 改写；共享后端同时只允许一个 owner/inflight。

驱动复用键为 CE session、逻辑源地址、版本、rows、K 与 Aq/Sa 物理地址。只复用已完成且仍有效的量化结果；新 session、错误、reset、绑定变化和 `nx_linear_input_invalidate` 都清除有效位。改写 scratch 的调用者必须先撤销借用。不同 shape/地址即使版本值相同也不命中。不用地址相同推断数据相同，不通过哈希代替生命周期合同。旧未标记调用始终重新量化。

直接输入只接受完整落在 `0xba000000..0xbc000000` 的 16 字节对齐 uncached 区域，要求范围不溢出、容量充足、CE idle、CPU 拥有输入，且不与输出 staging、结果、Aq/Sa 或模型重叠。`NX_OPT08_DIRECT_INPUT=0` 可回滚直接访问。不能证明一致性的 cacheable 输入继续 staging；不满足 16 字节对齐但可正常读取的输入继续 memcpy。部分 staging 别名、结果与源/私有输出/量化区重叠、非法 public job 等在提交前拒绝。实际 driver 仍验证所有 tensor、scratch 范围和模型 seal，仍执行原 fence/acquire/drain/release。输出回拷继续保留：外部结果仅在完成验证和释放 owner 后发布；硬件失败时先恢复 ownership 才可读取共享区中的旧结果。

当前生产 norm/KV/work 位于原有 AC/A8 arena，不能仅因 CPU 同步就声称直接访问已被采用；生产节省来自 Q/K/V、gate/up 跳过重复 staging 和量化。BA 直接输入是向 OPT10 交接的已验证能力。M4 只验证驱动/CE 对四行输入的版本、量化和输出，生产 `NX_PORTABLE` 仍为 M1；跨 token 的版本/批处理由 OPT13 承接。K65 在软件量化中按尾组处理，CE64 保留 K896/K4864 能力边界并在 dispatch 前返回 unsupported。

`nx_forward_token_v2` 使用 session 私有的完整 151936 元素 logits 并调用原 `nx_greedy`，不再把它复制到 T12 外部请求缓冲。`nx_logits_v2` 只返回成功且非空有效 session 的只读 view，生命周期到下一次 forward/reset/错误；诊断 dump 改为使用此 accessor。v1 `nx_forward` 仍按原合同复制到独立调用者缓冲。v2 不接受外部 logits 目的地址，因此不需要把 T12 的外部请求缓冲与内部原子发布区设为别名。错误撤销 accessor，可验证的最终输出和完整词表保留。`NX_OPT08_LOGITS=0` 回滚 adapter 的复制路径；`NX_OPT08_REUSE=0` 回滚 forward 的版本量化复用。

缓存数组放在 session 持久存储内；RV32 静态 state 容量提高到 16 KiB，KV/work arena 不变，不新增大型栈临时数组。生产 ILP32F 应用、诊断消费者和驱动需完整重新链接。64 KiB 栈检查与 ABI/静态内存证据由验收收据保存。

计账只消除每层三次 K896 输入量化/staging、每个已执行 head 的一次完整 logits 复制。每个 forward：七个层线性量化由 168 次减到 96 次，执行 head 时总量由 169 次减到 97 次；少处理 64,512 个激活，少写 64,512 字节 Aq 和 4,032 字节 Sa，少 staging 258,048 字节。每个 head 再少复制 607,744 字节。保留输出 staging 回拷、finite/argmax 扫描、head 计算；不重复计入未来融合、DMA 重叠或 OPT14 argmax 的收益。RV32 微基准周期必须保留其真实内存环境标签，不能直接替代整网 TTFT/decode 或实物 native DDR 时序。
