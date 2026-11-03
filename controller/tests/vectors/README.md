# Numeric v1 测试向量

`v1/small.npz` 是源码内版本化小矩阵，覆盖 ties-to-even、正负极值、零组、K=65 尾组、FP32 bias 与分组恢复。`make t05-test` 可独立核对，不加载真实权重。

`make t05` 使用固定模型锁生成完整真实尺寸向量并复制到 `evidence/T05/<run-id>/artifacts/vectors/`。重复运行不会覆盖旧证据。`index.json` 列出每个文件大小、SHA256、真实权重来源、case 的 M/K/N、输出分块数和尾块长度。依赖 NumPy 2.4.6、Torch 2.8.0+cu126、Safetensors 和本机锁定 FP32 权重；全部在 CPU 执行，无需 GPU/VCS/PDS。

| 路径 | 内容 |
|---|---|
| weights/{q,k,v,o,gate,up,down,head}/q.npy | INT8 W[N,K]，共享于三种 M |
| weights/*/scale.npy | FP32 Sw[N,ceil(K/64)] |
| weights/{q,k,v}/bias.npy | FP32 bias[N] |
| {name}-m{M}/x.npy, aq.npy, sa.npy | FP32 A[M,K]、INT8 Aq、FP32 Sa[M,G] |
| {name}-m{M}/dots.npy | INT32 [G,M,N]，仅组内累加，非跨组和 |
| {name}-m{M}/y.npy | FP32 [M,N]，按合同逐组恢复后一次加 bias |
| embedding.npz | token IDs、共享矩阵选定行的 q/scale 与解量化值 |
| block-m{M}.npz | 层 0 输入、逐算子中间值、cache_K/V、输出与 final RMSNorm |
| cache-chunks.npz | 同 8 个输入分 1+3+4 追加得到的输出和 cache |
| rope-positions.npz | 绝对位置 0/1/63/64/511/512/2047/32767 和 canonical inv_freq |

所有 NPY/NPZ 使用 `allow_pickle=False` 读取，逻辑张量为 C-order，整数 int8/int32、FP32 或 ID int64；本次小端主机写出小端多字节 dtype。NPY 头携带 dtype/shape/顺序，不是 T10 模型包 ABI。不得转置成后端排布后继续引用原始文件 hash。读取方须同时验证 index、模型锁、数值版本和阈值身份。

独立核对入口：`npu-python tests/vectors/check_v1.py <vectors-dir> --report <new-report.json>`。checker 从项目冻结阈值和锁定原权重验证，不接受索引自行声明的新容差。完整语义见 [numeric-v1.md](../../docs/spec/numeric-v1.md)。
