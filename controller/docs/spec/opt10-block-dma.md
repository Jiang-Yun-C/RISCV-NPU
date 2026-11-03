# OPT10 串行块供数合同

独立覆盖层 `variants/opt10` 叠加冻结 B 和 OPT08。CE descriptor/completion ABI、group64 INT32 点积和逐组 FP32 恢复顺序保持原版本。`SA_SCALE_BURST`、`WEIGHT_ROW_BURST` 为独立综合参数，默认 1；两个参数为 0 时保留 B 的逐字 Sa、逐组权重路径。已有 `SW_SCALE_BURST=1`、`M1_OUTPUT_PACK=1` 由真实事务验证，不能再次计作新收益。

Sa 以 4 字节 beat 合批，最多 32 beat，按 4 KiB 切分。每行权重预取以 16 字节 beat、最多 32 beat/512 字节及 4 KiB 切分，最后不足 16 字节按 4/1 字节处理。行步长继续为 padded K，预取只消费逻辑 K 字节，padding 不读取或参与点积。CPU 公共接口仍只支持 K896/K4864；K65/66/67 在私有生产 transport 的组件测试覆盖，不能据此扩大公共能力。

64 KiB scratch 继续为**单个 128 位同步 RAM 字节使能端口**，A/B 是逻辑 owner，不是两个物理端口。DMA 写 SRAM 时不允许控制器访问。量化 A、Sa、当前行权重和 Sw 先供数，随后串行点积、FP32 恢复和输出。没有 DMA/计算重叠；模型不得使用 `max(compute, transfer)`。

| scratch 字节范围 | 内容与最大占用 |
|---|---|
| 0000–4bff | 四行 Aq，4×4864 字节 |
| 5000–54bf | 四行 Sa，4×76×4 字节 |
| 5800–592f | 当前权重行 Sw，76×4 字节 |
| 5c00–5c03 | 当前 bias |
| 6000–64bf | 当前行四 token 的组点积 |
| 8000–92ff | 当前完整权重行，最多 4864 字节 |
| c000–d2ff | 既有 audit 记录 |

每个块的逻辑身份为 `(epoch, generation, M, N, K, padded_K, group_count, M_block, row)`，并绑定 Aq/Sa/Wq/Sw/bias/Y 物理范围、Y stride 和运行期限。OPT11 可接收完成量化后的只读 Aq/Sa 块及版本；在当前同步 owner 释放前不能改写。未来 SFU 若要求并行，须新定义实际 RAM 端口、银行映射、仲裁和提交/完成合同，不能直接复用逻辑 A/B 名称宣称并行。

CPU 在共享 AC/A8/BA 区域使用原 uncached/fence 协议；私有 cacheable 输入继续按 OPT08 staging 合同处理，不能仅加 fence 就开放 cacheable DMA。模型只读 sealed，输入及量化区在 lease 内不可改写，输出在成功完成、原 native **1024 周期 drain**、completion acquire/ACK 和 owner release 后才可读。stop/reset/timeout 不取消已接受的 AXI offer，保留 owner，待全部 R/B 和 native 写可见后复位。错误不允许 CPU fallback 掩盖。

计数器的 load/compute/write 继承 B 的 phase 边界；B 的 compute phase 内包含逐组权重供数，因此不能将它等同纯点积时间。独立 `timeline.csv` 记录状态驻留、DMA CMD/RESULT、native 行列/突发和 WLAST；`phases.csv` 保存 DUT 计数及独立握手/周期计数。load+compute+write+other 为互斥分区，restore 是嵌套观察，不能再加入总和。有效带宽用有用 payload/完整后端或完整线性调用周期，另列 native 实际总线字节及放大率；共享 DDR 竞争样本单列。生产 staging、量化和输出回拷由 OPT08 adapter 在采用本 RTL 的真实链路复验。

本合同只用于离线数字验证。125 MHz 是模型基准频率；PDS 集成时序/资源、DDR PHY 和板端带宽由 OPT16/17 继续验收。整网 TTFT/decode 预测保留 null，实物操作后置 OPT17。
