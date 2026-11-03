# T08 后端 API 合同 v1

version=backend-api-v1；numeric_version=`w8a8-g64-fp32-v1`（数值 ID=1）。
producer=T08；consumers=T10/T11/T12/T13/T14/T15/T19/T27。
[C 头文件](../../software/include/backend_v1.h) 冻结源码级调用，
[能力表](backend-capabilities-v1.json) 冻结计划范围和已有验证范围；
[系统合同](system-contract-v1.md) 与 [地址图](memory-map-v1.json) 共同适用。
本卡不提供运行时函数实现，不能把头文件编译通过表述为驱动/算子已经实现。

## 数据与调用语义

`nx_tensor` 的 address/allocation_bytes 是 SoC 物理地址和可访问分配长度（字节）；
桌面实现必须经 arena 解析。rank=1…4、shape 元素数为无符号正整数，stride 单位为**字节**。
dtype={I8=1,F32=2,U32=3}，layout_id=1 表示逻辑 C-order view，不是物理模型包 ID。
本版要求紧密连续、正 stride、无 broadcast/负 stride/转置，未用维度和 stride 必须清零。
所有 tensor 起始地址 16B 对齐，内层 stride 等于元素字节数；未来任意 stride 须能力升版。
span=`itemsize+Σ((shape[i]-1)*stride[i])`，用受检查 64 位运算，不能溢出或超过
allocation_bytes；整个 allocation 必须在同一个合法 DDR 分区。输出只允许 KV/workspace/shared_io，
tensor API 不用于访问 MMIO、CPU executable 或 loader 装载。输入也只能在这四个共享数据分区。
读只读权重合法；输出覆盖输入或其他输出一律拒绝，KV append 只写 cache 的新位置。
全零 tensor 是唯一“缺省”编码，只允许 linear.bias 缺省；必需 tensor 全零无效。

`nx_call` 包含 api_version=1、显式 route、session、sequence、timeout_ticks。
session 从 1 开始，每次成功 reset 严格加 1；sequence 每 session 从 1 严格递增。
拒绝阶段未接收的请求不消耗 sequence，已接收失败也不能重用；UINT64_MAX 后拒绝回卷。
timeout_ticks 为正，以 context 中与 stats.tick_hz 相同的单调参考时基计数，覆盖验证至完成；
超时不是“结果为空的成功”。上层请求总时限由 T12 另计，不能靠每个小调用重置时限绕过。

所有 run **同步阻塞**，每 context 只允许 1 个调用且全系统 Coral 同时 1 个 owner；无队列、
异步 callback 或必需中断。并发/重入返回 EBUSY。`nx_wait` 是对同 session 最近一次已接收
sequence 的结果查询，返回保存的 status/stats；活动调用时 EBUSY，过期/未知身份 ESTATE，
不隐式等待、不重复提交。`nx_reset_session` 在 idle 或故障恢复时调用；先按系统合同排空/隔离，
成功后新 session、sequence=0、KV 有效长度=0、清除旧完成记录。忙时 EBUSY，恢复失败保持
FAULTED。返回成功才允许释放所有权和使用输出；错误时 output_valid=0，即使物理内存已部分写入。

`nx_query_caps(route)` 返回**当前已安装并验收**能力；operation_mask 使用 `1u<<NX_LINEAR` 等位，
vector_mask 使用 `1u<<NX_EMBEDDING` 等位；未知 route 返回 EUNSUPPORTED。cap.max_m 等是上限，
K 白名单、紧密 stride、固定 GQA 形状等限制仍以本合同为准，上限不代表任意组合均支持。
静态 JSON 的 True 表示下游实现目标，不能未经 T11–T16 验收就上报实际能力；不存在实现时
不得假成功。CPU C 为功能回退，Coral 为唯一加速后端。
context 的创建、arena/时基绑定和模型加载属于 T12 runtime；opaque context 不能被序列化进
模型包或通过 MMIO 传输。C enum/struct 的宿主布局不是固件私有 ABI。

## linear_run

输入 A[M,K] F32、Wq[N,K] I8、Sw[N,K/64] F32、可选 bias[N] F32，输出 Y[M,N] F32。
group_size=64，M=1…512，N=1…151936，K∈{896,4864}；K 尾组本版不暴露。
这些是独立形状上限，仍必须通过实际 buffer 容量检查。512×151936 FP32 logits 为
311,164,928 bytes，超过 128MiB workspace，整块请求返回 EBOUNDS。默认生成只计算最后位置
head；若要全部位置 logits，调用方须切分 M 并消费/释放各块，不能跨分区申请或静默丢弃输出。
语义 Y=A×Wᵀ+b：入口 CPU C 动态量化为 Aq/Sa（计 quantize_ticks），然后按照 T05 顺序
执行 INT32 分组 dot、先乘 Sa 再乘 Sw、递增组累加、最后加一次 bias。
NaN/Inf、非法 scale、-128 和零 scale 对应非零 q 的处理完全遵从 T05，返回 ENUMERIC。
权重整体验证在 T10/T18 装载封存完成，run 仍验证输入/输出与调用时的动态数据。

Coral 生产调度以 N≤128、M=4 或 1 分块；剩余 2/3 行拆成多个 M=1，不假定 T07 验过 M=2/3。
生产 N 尾块 1…128 由 T15 验证；当前真实模型 N 均是 128 的整数倍。
T07 的 256 行 head 探针可作为已有证据，生产合同仍统一 ≤128。
最大 Aq/Sa 暂存是 `4*4864 + 4*76*4 = 20,672 bytes`，剩余 DTCM 12,096 bytes 供栈/参数；
该算式不代表固件实际 footprint 已合格，T14 必须检查链接 map 和保护区。
每块保留全部 K/所有组和 FP32 恢复顺序。Y 的全局行 stride 为 N*4，driver 传入 tile 的
output row stride，不能把不同 token 的 N 子块错误写成紧密小矩阵。
Q/K/V、gate/up 入口量化可复用，必须绑定相同输入内容和 session 并计一次成本；初版允许不复用。

CPU_C 路由按同一接口计算，用于 T11 参考或显式回退。runtime 在提交前选择 route；不支持的
合法形状/布局返回 EUNSUPPORTED，由 runtime 记录原因后选择 CPU 支持路径或拒绝。
EFAULT/EIO/ETIMEOUT/ENUMERIC 不自动转 CPU 隐藏故障；必须记录失败，恢复会话后才能重试。

## attention_run 和 vector_run

attention 仅 CPU_C：Q[M,14,64] F32、K/V[capacity,2,64] F32，输出 Y[M,896] F32。
1≤M≤512，capacity=640，past≥0，past+M≤640；KV 已追加本 chunk，仅读到 past+M。
函数包含 QK→因果 Softmax→PV，head h 使用 KV head floor(h/7)、QK 除 8、mask s≤past+t，
全部 FP32 规约与 T05 一致。三个子阶段分别记 trace，父调用时间不可再与子阶段相加。
Coral attention 返回 EUNSUPPORTED；未经新能力验收不切换到 RVV/VME。

vector 仅 CPU_C，下表 slot 固定；unused tensor/属性必须全零。所有 F32 操作遵从 T05，
input_count/output_count 严格匹配。下表 M=1…512，H=896，F=4864，G=ceil(K/64)。

| opcode | inputs 按顺序 | outputs 按顺序 | 属性/语义 |
|---|---|---|---|
| EMBEDDING | ids[M] U32、Wq[151936,896] I8、Sw[151936,14] F32 | hidden[M,896] F32 | ids<151936，按组解量化；共享 head 权重 |
| RMSNORM | x[M,D]、gamma[D] F32 | y[M,D] F32 | D=896，epsilon=1e-6，T05 规约 |
| ROPE | q[M,14,64]、k[M,2,64] F32 | qrot、krot 同形状 F32 | past+M≤640，capacity=640；theta=1e6，配对(i,i+32) |
| KV_APPEND | krot[M,2,64]、v[M,2,64] F32 | cacheK、cacheV[640,2,64] F32 | past 为当前有效长度，capacity=640，append 后有效长度 past+M；旧位置保留 |
| ADD | x[M,D]、z[M,D] F32 | y[M,D] F32 | D=896，禁止 in-place |
| SWIGLU | gate[M,4864]、up[M,4864] F32 | y[M,4864] F32 | 稳定 sigmoid/silu 再乘 up |
| ARGMAX | logits[151936] F32 | token[1] U32 | 同值最小 ID；runtime 判 EOS=151645 和 128 token 上限 |
| QUANTIZE | a[M,K] F32 | aq[M,K] I8、sa[M,G] F32 | K∈{896,4864}，g64；作为 linear 子阶段记录 |

KV 各层独立、连续追加，先写当前 chunk 再算 attention。若层中途失败，整次推理请求失败，
不得复用半更新 KV；reset 后重新 prefill。内核可按行/块算 attention，禁止为了缩小窗口改变
因果或 GQA 语义。ARGMAX 只处理完整最后位置词表，不能截断词表或丢弃 EOS。

## 整网执行与回退成本

[能力表](backend-capabilities-v1.json) 中 `operations` 与 T05 execution 逐项同序，
24 层重复展开共 412 个逻辑阶段，其中 169 个 linear、243 个 CPU 阶段。
QK/softmax/PV 共同归属一个 attention 调用，按子阶段记录，不能把三个阶段当作三次完整 attention。
每个目标调用附 session、sequence、layer、operator、shape、route、fallback_reason、状态与计数；
这些 trace 元数据由 runtime 持有，避免把层号硬编码到驱动 ABI。

| T05 阶段 | 执行路径 | 必记成本 |
|---|---|---|
| embedding | vector/CPU C | gather、解量化、CPU ticks |
| input/post/final RMSNorm | vector/CPU C | FP32 规约/sqrt/scale、CPU ticks |
| Q/K/V/O/gate/up/down/head | linear/Coral RVV | CPU 动态量化、上传、控制/等待、结果回收、核心周期/AXI 字节 |
| RoPE | vector/CPU C | 位置函数/旋转、CPU ticks |
| KV append | vector/CPU C | 复制写入 bytes 和 CPU ticks |
| QK、causal softmax、PV | attention/CPU C | 各子阶段 ticks、MAC、KV/scores 工作集 |
| 两次 residual | vector/CPU C | FP32 add、CPU ticks |
| SwiGLU | vector/CPU C | sigmoid/silu/mul、CPU ticks |
| greedy/stop | vector/CPU C＋runtime | 完整 logits 扫描、停止判断 ticks |
| tokenizer/协议/控制应用 | runtime CPU，模型阶段表之外 | scope-timing-v1 单独区间，纳入请求端到端 |

所有 CPU 行为是已选择的基线路径，非“免费操作”；C/RV32 尚待 T11/T12 实现，静态表的
measured_target_ticks=null 表示未测，不能写 0。即使主控 FPU 尚未验收也须用软浮点保持语义，
性能实测后再决定优化，不改变数值或比较负载。
fallback_reason=0 表示 Coral 正常路径，1 表示表中固定 CPU 阶段，2 表示能力不支持后的
显式 CPU 回退，3 表示用户/评测配置选择 CPU 对照；必须记录最初拒绝原因及最终 route。

## 性能计数

`nx_stats` 64 位计数，失败也返回已采集部分；valid_counters 位区分未测与真实零。
elapsed_ticks 从函数入口至返回，单一单调参考时基 tick_hz；仿真注明时钟和模式，桌面可用 ns。
validate/quantize/upload/execute/download/fallback/other 为**不重叠**区间，总和必须等于 elapsed。
Coral execute 包含启动、等待、轮询与排空；CPU route 的数值执行计 fallback，execute=0。
动态量化作为 linear 子区间，不再叠加内部 QUANTIZE trace；纯 CPU linear 同样遵守。
backend_cycles 是 Coral 核心 mcycle 差，不能与参考 ticks 相加；时钟域/门控/频率须记入 trace。
64 位读取用高/低/高一致性方法；只读到低 32 位时不得默认为完整计数，必须分段防回卷或报不可用。
AXI read_bytes 为 R 握手有效负载、write_bytes 为 W 握手 WSTRB popcount，统计区间注明调用；
包含校验/debug 传输则单列模式，不能删掉对应 cycles。upload/download 字节另计主控到从口流量。
MAC 仅数学乘累加，linear=M*N*K；attention QK/PV 各 `896*Σ(past+t+1)`；CPU 非 MAC
算子记录 ticks 而非伪造 MAC。总端到端和 TTFT/decode 仍按 scope-timing-v1，不把阶段时间重叠求和。

## 错误码与原生启动

| 返回码 | 含义 |
|---|---|
| 0 OK | 输出完全可见且有效 |
| -1 EINVAL | 零维、错误 rank/dtype/opcode 参数/计数等畸形请求 |
| -2 EVERSION | API/numeric/pack 版本不兼容 |
| -3 EUNSUPPORTED | 合法但未支持的 route/shape/stride/layout/操作 |
| -4 EBOUNDS | 地址、长度、span、权限、重叠、位置越界或整数溢出 |
| -5 EALIGN | tensor 或入口地址未按要求对齐 |
| -6 EBUSY | context/全局后端已有 owner |
| -7 ETIMEOUT | 正时限耗尽，进入故障恢复 |
| -8 EFAULT | 核心 fault 或异常结束/完成身份不匹配 |
| -9 ENUMERIC | 非有限数、非法量化输入或结果 |
| -10 ESTATE | session/sequence/KV 状态错误或上下文故障未恢复 |
| -11 EIO | AXI SLVERR/DECERR、上传/回读/模型校验失败 |

检查次序：版本→状态/身份→参数→地址/权限/对齐→能力→数值；多个错误按先检测者返回。
参数/能力拒绝不启动硬件、不修改输出。Coral 从口 CSR 本地 +0x30000：control +0 bit0 reset、
bit1 clock gate，初值3；entry_pc +4；status +8 bit0 halted、bit1 fault。
驱动在安全 idle 下写 control=3，上传经校验的程序/参数，清除完成记录并写当前 session/sequence，
写本地 entry 并回读，再写 control=0 启动。参数/完成记录由 T13 固件定义 version/size、
session/sequence/status，属于该固件私有 ABI，不能作为通用 64B descriptor 或模型包头。
完成按系统合同检查并排空；fault 优先于 halt。轮询原生状态即可，首次接口不要求中断。
程序应使用已验收的 mpause 退出；WFI 不是成功。32 位 CSR 写转 128 位时以地址低四位选
lane 和 WSTRB，例如 entry +4 的数据在 bits63:32、WSTRB=0x00f0。

T13 验桥接/故障/所有权；T14 验实际 footprint/分块地址；T15 验各线性/stride view 适配和数值；
T16 验真实主控闭环。`make t08` 只验合同、自洽性、地址/参数边界和 C/RV32 头文件可编译。
