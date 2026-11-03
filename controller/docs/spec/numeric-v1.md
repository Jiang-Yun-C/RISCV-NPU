# T05 数值合同 v1

版本 `w8a8-g64-fp32-v1`。Producer=T05，consumers=T07/T10/T11/T15/T19。变更必须新版本、说明原因、冻结阈值并重跑受影响的向量、导出器、算子和模型质量；不能因后端失败修改容差。此合同规定逻辑张量，物理打包及后端能力由 T08/T10 定义。

## 模型、算子和生成

输入唯一身份为 [T02 v2 模型锁](application-v2-model-lock.json) 的 **LoRA 合并 FP32** 权重与原始 tokenizer。不能换成未适配 base。实际 checkpoint 的 290 个张量、形状、dtype 和共享别名在 [operator-manifest.json](operator-manifest.json) 中，复跑逐项核验。

网络为 24 层、hidden=896、FFN=4864、Q heads=14、KV heads=2、head_dim=64、词表=151936；全注意力，RoPE theta=1e6，无位置缩放、无滑窗。结构依据 [固定 revision 配置](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct/blob/7ae557604adf67be50417f59c2c2f167def9a775/config.json)；算子顺序同时核对本机锁定版本与 [Transformers 4.57.6 Qwen2 源码](https://github.com/huggingface/transformers/blob/v4.57.6/src/transformers/models/qwen2/modeling_qwen2.py)。部署数值格式为本项目定义，不声称是框架默认量化格式。

| 执行顺序 | 输入 → 输出 | 算术与参数 |
|---|---|---|
| embedding | token[T] → hidden[T,896] | INT8 共享矩阵按行取出，以该行每组 FP32 scale 解量化；不做 embedding A8 |
| input RMSNorm | hidden → norm1 | FP32 mean(x²)，epsilon=1e-6，rsqrt 后乘 gamma |
| Q/K/V | norm1 → [T,14/2/2,64] | W8A8，Q bias[896]，K/V bias[128]；bias 保持 FP32 |
| RoPE | Q,K → Qrot,Krot | 每头配对 (i,i+32)，不是相邻偶奇；V 不旋转 |
| KV append | Krot,V → cache[S,2,64] 各一份 | FP32，绝对位置 past+t，先写本 chunk 再做因果 mask |
| QK / Softmax / PV | [14,T,S] → [T,896] | FP32，QK 除以 8；头 h 使用 KV 头 floor(h/7)；s≤past+t；减最大值后 exp/sum/divide |
| O 投影 / 残差 | attn → res1 | W8A8 O 无 bias；与本层原输入作 FP32 加法 |
| post RMSNorm | res1 → norm2 | 独立 gamma，epsilon=1e-6 |
| gate / up / SwiGLU | norm2 → [T,4864] | 两个无 bias W8A8 投影；FP32 silu(gate)×up |
| down / 残差 | act → hidden_next | W8A8 down 无 bias；与 res1 作 FP32 加法 |
| final RMSNorm / lm_head | 最后层输出 → [M,151936] | final gamma；无 bias W8A8 head 与 embedding **同一份量化权重及 scale** |
| greedy / stop | 最后位置完整 logits → token | 最大值相等选最小 ID；EOS=151645；新生成最多 128 token |

重复层内步骤 24 次；残差、norm、attention、SwiGLU、KV 均为 FP32，只在线性层入口动态量化 A8。decode 可仅投影最后位置；prefill 若请求所有 logits，必须明确 M。token ID 包括整个 151936 行的 logits 候选，不擅自裁掉 tokenizer 不常用的保留行。

生成沿用 T02 实际 resolved 配置：greedy、beam=1、repetition_penalty=1、`use_model_defaults=False`；输入最多 512，加输出最多 128，总 KV 容量至少 640。151643 是 BOS/PAD，**不是本次冻结的 EOS**。返回完整输出 token 及停止原因；最后第 128 个 token 若是 EOS，则记 eos，否则 max_new_tokens。达到长度上限不是应用验收成功。模型文件自带的 do_sample/repetition_penalty/多 EOS 默认值不得回填。聊天模板、UTF-8、tokenizer 与程序语义按 [应用协议 v2](application-v2-contract.md)。

## W8A8 分组、舍入和异常

逻辑矩阵 A[M,K]、W[N,K]、Y[M,N] 均按行描述，Y=A×Wᵀ+b。每个 activation row 和每个 weight row 沿 **输入 K** 独立分组，G=ceil(K/64)；scale 分别是 Sa[M,G]、Sw[N,G]。Q/K/V 共享输入可复用同一 A8/scale；gate/up 同理。

所有正常浮点步骤使用 IEEE-754 binary32、round-to-nearest ties-to-even，禁止 FP16/BF16/TF32、flush-to-zero 和默认 FMA 重关联。FP32 运算生成非有限值时整个调用失败；调用方不得提交部分输出。输入转换成 FP32 后仍须有限；NaN/Inf、负 scale、subnormal scale、-128 整数和形状不符一律拒绝。

对每行每组：

1. `amax=max(abs(x))`，只统计有效 K；尾组右侧按零填充，填充不进入有效长度。
2. amax=0 时，scale=+0，q 全为 0；scale=0 且任一有效 q 非零的外部数据非法。
3. 否则 `scale=max(FP32(amax/127), FLT_MIN_NORMAL)`，FLT_MIN_NORMAL=2^-126。这样最小正输入也不会因 scale 下溢变成非法零组；极小非零元素量化成 0 是允许的量化损失。
4. `q=INT8(clamp(round_even(FP32(x/scale)),-127,127))`，zero_point=0，范围为 [-127,127]，不使用 -128。
5. scale 保存 FP32。解量化是 `FP32(FP32(q)*scale)`；符号零在整数侧统一为 0。

线性层按 g 从 0 递增：

```
acc_g = Σ有效k INT32(Aq[m,k]) * INT32(Wq[n,k])
p_g   = FP32(FP32(acc_g) * Sa[m,g])
v_g   = FP32(p_g * Sw[n,g])
y     = FP32(y + v_g)                  # y 从 +0 开始
y     = FP32(y + bias[n])              # 全部组之后，且仅一次
```

不得把所有 acc_g 先加起来再乘某一个 scale；也不得先将 Sa×Sw 相乘、融合乘加或更换跨组顺序来声称逐位符合。后端可在已冻结浮点容差内采用其他 FP32 实现，但同一输入的量化整数、scale、组内 dot 必须逐位一致，且必须保留每组恢复语义。只有 per-tensor scale 的后端必须报告按组拆任务、搬运及主控恢复开销；不能拿不同数值格式直接对比。

INT32 推导：每乘积绝对值≤127²=16129，64 项组内绝对值≤1,032,256<2²⁰<2³¹−1，负侧同样安全；尾组 L 项≤L×16129。组内 dot 转 FP32 也精确，因为绝对值<2²⁴。K=896 为 14 组、4864 为 76 组；v1 不依赖全 K 整数累加，即使这些形状全 K 仍未溢出，跨组 scale 不同也不能合并。任意 K 都重置组内累加器，因此不把 INT32 安全性绑定到当前模型。

## FP32 非线性和 cache

RoPE 的 `inv_freq[i]=FP32(1 / FP32(1e6^(2i/64)))`，i=0..31；角度由 FP32 position×inv_freq 产生，cos/sin 复制两半，输出 x×cos+rotate_half(x)×sin。测试同时导出 canonical inv_freq，后端应复用同一表，避免 pow 在不同平台的末位差异被长位置放大；三角函数用 FP32 并按算子容差检查。位置范围 0..32767；运行时 640 token 上限更小。

参考对 RMSNorm、QK、Softmax 分母、PV 的 FP32 reduction 固定使用相邻配对二叉树：归约维右补零到下一 2 的幂，先相加 (0,1)、(2,3)…，再重复配对，乘积先独立舍入。RMSNorm 用 tree_sum(x²)/hidden 得到 mean，再 `x*(1/sqrt(mean+1e-6))*gamma`，每步 FP32；不能假设融合 rsqrt 与两步 sqrt/reciprocal 逐位相同。后端其他规约算法仍须同时通过局部和累计门槛；动态 A8 的半整数边界会放大上游末位差异，仅局部浮点接近不保证整层通过。

Softmax 的 mask 独立表示为布尔值，内部允许 -Inf sentinel；用户输入非有限值仍拒绝，全 mask 行拒绝。允许 exp 的正常下溢为 0；SwiGLU 使用 `e=exp(-abs(gate))`，正侧 sigmoid=1/(1+e)、负侧=e/(1+e)，先乘 gate 后乘 up。FP32 残差不得提前量化。独立累计检查器使用同一规约和运算顺序的 Torch CPU 实现；局部算子还与框架普通算子交叉比较。

KV 存旋转后的 K 与未旋转 V；每层两份 [S,2,64]，未扩展成 14 头。prefill 多行和 decode 单行按相同绝对位置写入，因果掩码包含当前位置。会话 reset 清空有效长度，旧值不可读取；v1 不做 KV 量化或窗口丢弃。非法长度、位置或不连续 append 拒绝。T05 验证单层分块 1+3+4 与一次 8 token 的结果，完整 24 层 teacher forcing 由 T11/T19 验收。

## 误差和质量门槛

[t05-thresholds.json](../../configs/t05-thresholds.json) 是唯一机器可读阈值，所有值在首次后端执行前固定，没有待填项。每次证据在运行前记录其 hash 并保存副本。整数 mismatch=0，scale bitwise_equal；FP32 必须同时满足所有元素 `abs(error)≤atol+rtol*abs(reference)` 和 NRMSE 上限；NaN/Inf 总是失败。NRMSE 分母为 max(RMS(reference),1e-12)，另报告最大绝对/相对误差和 RMSE。

算子 atol/rtol/NRMSE 分别固定；例：linear=2e-4/2e-5/2e-5，RMSNorm=2e-5/2e-5/1e-5。累计 block/KV=2e-3/2e-4/1e-4，24 层 logits=1e-2/1e-3/5e-4。工程容差允许 FP32 reduction 与 libm 的末位差异，**不是从硬件失败或保留集反向拟合**。T05 用独立 Torch CPU、单层及分块敏感性验证；24 层门槛先冻结，达标性由 T11 验证，尚不宣称整网通过。

固定 token 的 8 步 teacher forcing、上下文 1/4/8/512 为下游必测；输入 ID 完全相同。当 reference 第一/第二 logit 间隔>2×最大绝对误差时 argmax 必须相同，其余翻转也必须记录并进入自由生成质量评测，不能用“在容差内”免除质量门槛。

量化损失与后端实现偏差分开：向量报告量化输出对原 FP32 权重（FP64 点积测量）的误差，该数值不使用后端容差判断。模型质量比较必须使用同一适配模型、tokenizer、协议、split 与 greedy 配置：合法≥90%、相对浮点下降≤3 个百分点；正确拒绝≥95%、下降≤3 个百分点；传感器成对=100%、EOS=100%。先跑 dev，再冻结版本后作最终评测；禁止 v2 heldout 参与校准、调参、候选选择。T05 不执行保留集推理，不声称 W8 模型质量已通过。

## 向量、执行及覆盖

```
make t05                 # 新证据目录：身份、生成、独立核对、全量复生、项目回归
make t05-test            # 数值边界与损坏证据负例，不加载完整模型
make t05-capacity        # 逻辑容量 / 访存 / MAC，可另传 --context / --m
```

[Python 数值参考](../../model_tools/numeric_v1.py) 不导入 Torch、Transformers 或后端。真实矩阵使用层 0 的七个投影与共享 embedding/head，每个 M=1/4/8，共 24 例；N=128/896/4864/151936，K=896/4864。head **全词表输出**，N tile=256，594 块，末块 128；896/4864 也有 128 行尾块，K 实际均为完整 64 组；小矩阵单独覆盖 K=65 尾组。测试激活是固定种子合成数据，单层输入来自固定 ID 的实际量化 embedding，不读取应用数据集。选中一层的权重不是全部 24 层量化验收。

向量包含 A FP32、Aq、Sa、Wq、Sw、bias、每组 INT32 dot 和 Y FP32，以及单层全部中间输出、FP32 KV 和长位置 RoPE；[格式说明](../../tests/vectors/README.md)。真实尺寸权重在每个 family 内共享一次；大向量保存在 evidence，不复制到源码样例目录。完整模型的所有张量形状/dtype、模型文件和 tokenizer 文件 SHA256 均检查。

独立检查器不导入参考实现：小向量用 Python scalar round/任意精度整数求和；真实尺寸用 Torch 重新量化原权重，以 FP64 GEMM 计算精确组内整数 dot，再重放 FP32 恢复。FP64 组内整数和<2²⁰，可精确表示。另用 Torch 算子分别对照相同中间输入和完整层串联；以损坏的整数、scale、浮点结果验证检查器拒绝错误。重复生成比较每个文件 SHA256。

## 容量和访存计算

[capacity.py](../../model_tools/capacity.py) 从机器清单求和；共享矩阵只算一次，所有 bias/norm 保持 FP32。输出 W8+scale+小张量精确逻辑字节数，context=512/640/2048 时的 FP32 KV、M=1/4/8 的线性和因果注意力 MAC，以及理想矩阵/KV 复用与不复用时的流量公式。

这些是逻辑下界与明确的访存调度算式；不含物理包头/对齐、tokenizer、软件、激活生命周期和 DMA 工作区。1GiB 减去权重/KV 的差额不是已验收峰值余量。T10/T12 必须用实际包、分配和访存替换估计；板容、带宽、FPGA 性能仍待后置任务。
