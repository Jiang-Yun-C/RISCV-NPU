# T11 完整 C W8 参考合同

producer=T11；consumers=T12/T15/T19/T25。输入固定为 T10 发布 manifest 的完整适配模型包，
数值版本保持 `w8a8-g64-fp32-v1`，所有容差/质量阈值继续使用 `configs/t05-thresholds.json`。

## 执行与接口

`firmware/runtime/reference/nx_reference.c` 实现完整 24 层前向、14:2 GQA、半头 RoPE、
树形归约、稳定 Softmax/SwiGLU、FP32 KV、共享 embedding/head、bias、残差和完整词表投影。
`nx_generate` 在 C 内完成分块 prefill、greedy（并列选最小 ID）、EOS 和 128-token 停止。
Python 仅负责包校验/只读映射、原始 tokenizer、测试调度、解码文本和独立评分；不替代前向或生成控制。

主机 adapter 先调用 T10 独立读取器验证固定整包 SHA256、元数据、目录及数值，再向 C 提供
密封只读视图。C 的 `nx_weights` 是已验证 view ABI，不是任意二进制包解析接口；视图的有效
存储长度、数值合法性与整个会话期间不可变由 owner 保证。C 初始化另检查所有固定模型尺寸、
bias 配置和非空指针。T12/T18 需要提供自己的 RV32 装载/封存适配，不能直接接受未校验指针。

`nx_forward` 每次追加 1..8 个有效 token ID，past 必须等于当前长度，KV 上限 640。
返回 `NX_ARGUMENT=-1`、`NX_NUMERIC=-2`、`NX_MEMORY=-3`（保留）或 `NX_STATE=-4`；
创建失败返回 NULL。数值失败使 session 无效，必须 reset；公开 logits 不发布部分结果。
reset 清零有效长度，旧 KV 不能通过 host adapter 读取。无效参数不提交追加。
`nx_generate` 输入 1..512 token；成功后一起发布输出 token/count/stop，EOS 固定 151645。

## 浮点和独立对照

编译使用 `-fno-fast-math -ffp-contract=off`；round-to-nearest ties-to-even。
INT8 动态量化、FP32 scale、INT32 组内 dot 与逐组恢复顺序严格复用 T05；不使用 FMA 重关联。
整数 SIMD 只改变精确整数求和次序，不改变按 g 递增的浮点恢复。

超越函数采用：输入已为 FP32，使用 double libm 计算 exp/sin/cos，然后立即舍入为 FP32。
这避免不同单精度近似的末位差异跨越下一层动态量化边界；张量、乘加、归约、KV 均保持 FP32，
不改变阈值、不调整量化参数。独立 Python graph 用 NumPy double 超越函数后转换 FP32，
不调用 C 库、不接收候选值、不从 DUT 构造 golden；普通 T05 算子容差也单独复验。

Python oracle 使用独立 NumPy 图、冻结 canonical inv_freq，和禁用 TF32 的 Torch FP32
64 项整数 GEMM。每个乘积及任意部分和均在精确整数范围内（绝对和≤1,032,256），因此
它是 INT32 dot 的精确独立计算；跨组恢复仍按冻结次序分步执行。CUDA 只是加速测试 oracle，
C 推理全部在 CPU。独立实现不意味着使用另一份未知模型或更改数学规则。

验证先生成 golden 文件再调用 C。比较所有层中间输出，另外检查全层 KV 和完整 151936 logits，
冻结的逐元素误差与 NRMSE 必须同时通过；报告首个 context/position/layer/stage/index。
argmax 的 margin 规则、所有翻转、8 步 teacher forcing、上下文 1/4/8/512 都必须记录。
T05 的全部 24 个真实尺寸线性案例另外检查每个 Aq、Sa 和 INT32 dot，不能用文本合理替代。

## 质量、复生和交接

`make t11` 新建 build/evidence/受管理 traces 目录，执行源码/包身份、C 编译、算子、整网数值、
第二次独立重建与复生、fixture 自验、负例/项目回归、开发集、冻结、保留集、独立进程 token 复跑。
同 split 浮点参考使用已封存 T02 v2 的逐样例结果，先核对 artifact hash 与完整输入 token 一致性；
不把不同 split 的百分比直接比较。开发集通过后冻结源码/库/包/阈值/结果身份，保留集不参与选择。

`tests/cocotb/fixtures/golden/manifest.json` 发布小型独立 traces、数据类型/shape/stride/端序、
模型包与阈值 hash、生成器/checker 身份。`tests/reference/fixture_io.py` 可直接在桌面或 cocotb
scoreboard 中加载和比较实际候选 trace，缺阶段、错误整数/scale、非有限值或浮点超限均失败。
线性 fixture 的 W/Sw 由 manifest 中的 T10 包 tensor name/hash 定位；block fixture 从同文件
input_ids/past 和先前连续 case 重放。完整上下文与全部 token traces 在
`models/reference-v1/<run-id>/primary/`，文件列表及 hash 由证据 manifest 固定。

C 记录 embedding/norm/linear/RoPE/attention+Softmax/SwiGLU/residual/head 的 CPU 墙钟累计；
记录 session heap 的实际 sizeof、只读包映射、每线程显式 scratch 上界及主机峰值 RSS。
这些是桌面执行测量，Python/tokenizer/测试框架 RSS 不冒充 RV32 内存峰值。OpenMP、POSIX
计时和主机映射为桌面适配；T12 需移植、检查栈/堆峰值与 tokenizer，T15/T19 负责实际 RTL 消费。
本任务不需要 VCS 跑完整对话，也不验收 PDS、DDR 实物容量、FPGA 或板端性能。
