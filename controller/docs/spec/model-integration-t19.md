# T19 模型运行时集成合同

T19 接收 T05 冻结阈值、T10 原始 W8 包、T11 独立 traces、T12 同源 C/RV32 数值图、T16 真实主控/Coral 平台。配置为 `configs/t19-model-integration.json`，入口 `make t19`；结果以实际证据为准。

`nxr_coral_backend` 和 `nxr_coral_linear` 将完整逻辑 linear 绑定到 `nx_bind_backend`。输入先复制到非缓存共享工作区；主控动态量化，实际 Coral 微程序执行所有 INT32 dot、FP32 恢复和 N/M 分块；驱动确认 halt、ABI/session/sequence、完整写回及总线 drain 后，主控复制结果回数值图。硬件错误使 session 失效，不以 CPU 回退遮盖。仅未支持形状可以返回 `NX_UNSUPPORTED` 并在执行前回退。RMSNorm、RoPE、softmax/attention、SiLU、residual、embedding 和 KV 管理由真实 CPU 执行。

生产几何与 ABI 保持 24 层、H896/F4864/V151936、14:2、D64、640 槽物理 KV；请求层总长度仍为 T12 的 512。主控采用 T16 已验收的 RV32IMF/ILP32F 候选；编译依赖、入口和 FPU 初始化固定，不把 T12 软件浮点结果直接当硬浮点证据。

| 路径 | 执行内容 | 独立期望 | 范围 |
|---|---|---|---|
| block | 真实层 0，H896/F4864、14:2 D64；七个完整真实尺寸算子 | T11 发布 `context1-chunk000.npz` 逐阶段与 KV | 单 token、一个真实 block，无完整词表投影 |
| reduced graph | 2 层、H112/F128/V129、14:2 D8；共享 embedding/head | 独立 Python FP32/tree 数值图 | 同结构缩小整网，非完整 0.5B |
| continuous | reduced graph 连续 9 个固定 token，再溢出拒绝、reset 后两个新 token | 全阶段、logits、全部已用 KV | 跨第 8 个 token；9 槽物理容量上限；N128 分块与 N129 尾块 |
| desktop | 完整 24 层 0.5B，全部 99 份 T11 traces、context=1/4/8/512 与每组 8 步；实际填满 640 后拒绝 | 原始 T11 不可变 traces，原包身份 | 桌面 C 数值，不提供 RTL/板级整网性能 |

缩小几何仅由显式测试编译宏 `NX_T19_MINI` 启用；真实 block 用 `NX_T19_BLOCK`。缩小图允许 逻辑 K112/K128，K112 在共享边界零填充至 K128，仍运行原封不动的 T15 微程序；生产 provider 继续只接受 K896/K4864，公共能力合同不扩充。默认 0.5B 和 T12 的 `NX_SMALL` 几何不变。

KV 仅分配 `[K/V, layer, capacity, 2, D]`，attention 用 `query_head / 7` 取 KV。检查器禁止主控向超出这一物理 KV 区域的地址写 KV，逐 token 比对已用前缀，重置后从位置 0 重新生成；不要求擦除旧物理存储，旧内容不得参与新会话。

PRELOAD 只初始化固件、不可变权重和 guard，不填输出、logits、KV 或分层期望。cocotb 仅等待、只读观察及检查环境；全部提交和数值图由真实 CPU 执行。DPI 只复用已验收的 Coral SRAM 存储模型，无算术替身。

整数/scale 逐位比较；各阶段同时使用冻结逐元素与 NRMSE 门槛。记录 token、layer、stage、执行方、首次不同元素。AXI 检查还核对实际提交形状/地址、CPU 量化、Coral 读取、每个实际 Y 写回及 CPU 读回、所有权和 drain。每次 native launch 保留前 5000 周期 VCD 窗口并与事务 CSV 对照；初始窗口 10000 周期。覆盖不包含未记录的全程波形。

短测 seeds=1/7/19 与 seed1 重跑；长测 seed1。独立负例保留 held-reset、bad-golden、bad-kv、empty、missing-xml 的原始 FAIL。归档复验拒绝缺失、重复、缩减矩阵、改写配置或任意输入/输出/hash 不一致。

producer=T19；consumers=T20/T21/T25。T21 回归同一矩阵；T25 接实际板端完整模型与真实 DDR。缩小整网和层片段不构成完整 0.5B RTL/FPGA 推理验收。
