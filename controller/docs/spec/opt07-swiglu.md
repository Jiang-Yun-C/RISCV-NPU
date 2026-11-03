# OPT07 SwiGLU 软件数学合同

该覆盖层从 OPT05 冻结的 B 创建隔离候选。根目录 A、B 原参考、T05 阈值、group64 量化及整数点积规则保留。生产 ABI 为 RV32IMF/ILP32F、GCC 14.2、O2、禁止 fast-math 和 FMA 收缩。

`nx_opt07_configure(mode,force_reference)` 必须在没有活动 forward 时调用。mode 0 为保留的 double exp 参考，1 为 expf，2 为 LUT 四阶多项式，3 为带结果区间检查的保守 LUT。非法配置返回 NX_ARGUMENT，不改变已有配置。`force_reference=1` 或编译 `NX_OPT07_DEFAULT=0` 均可回退。默认值为 3；最终生产 ELF 另用选定 mode 的显式编译定义绑定。

所有模式先完整检查两个输入的有限性，再写输出。NaN/Inf 返回 NX_NUMERIC；结果溢出也返回 NX_NUMERIC。输入参数与最大长度沿用原实现。原地 gate 输出合法；部分重叠数组不在合同内。保持 `gate>=0` 的稳定符号分支以及 `(gate*sigmoid)*up` 的两次独立 FP32 乘法，包含负零。

LUT 为 `exp(-i/16)`，i=0..256，每项从独立 binary64 libm 舍入为 FP32，总计 1,028 字节。范围内令 `i=trunc(16*abs(gate))`，`r=abs(gate)-i/16`；乘以 `1-r+r²/2-r³/6+r⁴/24`。二进制网格的范围缩减精确。范围外使用原 double exp，不人为提前截断负尾；原 exp 舍入的下溢结果可继续被大的 up 放大。

模式 3 对负 gate 使用原参考。非负 gate≥17 时，`exp(-gate)<2^-24`，FP32 舍入的 `1+e` 为 1，保留乘法顺序直接计算结果。gate∈[0,16] 时，以 LUT 的正、正规 FP32 exp 值为中心，在位表示上向上下各扩展 32 ULP，分别计算完整 sigmoid 和两次乘法。只有两个最终结果的位表示一致才接受；否则以及 gate∈(16,17) 时回退原 double exp。有限输入的这些舍入运算对 e 单调，up 的符号只改变单调方向。因此相同端点结果覆盖整个区间的舍入结果，最终不是输出近似值。

区间余量以 round-to-nearest、IEEE FP32 为条件。取 u=2^-24；四阶 Taylor 的相对截断余项小于 `exp(1/16)*(1/16)^5/120 < 8.5e-9`。包含 FP32 系数、Horner 运算、表项及末次乘法，使用 gamma(12)=12u/(1−12u) 和绝对系数和上界，再除以 exp(-1/16)，保守相对误差小于 1e-6。32 ULP 的最小相对覆盖约为 32u=1.907e-6，并留有原 binary64 exp 到 FP32 舍入的余量。该误差分析与大样本差分、每个网格边界相邻值、实际 RV32 输出及完整模型逐层比较共同验收；它不替代对未来 SFU 的舍入/次正规数行为验证。

独立 golden 使用 NumPy binary64 exp 后立即舍入 FP32，再执行原稳定分支及乘法。局部、block、KV、24 层 logits 和长度 1/4/8/512 的八步 teacher forcing 均沿用 T05。量化检查使用实际输入的独立整数和逐位 scale 计算；与原参考激活的量化差异另行记录，不能当作修改舍入规则的理由。dev 用于选算法，最终质量 heldout 在源码、库、dev 与 RV32 周期选择冻结后评估。

VCS+cocotb 为必测主入口，真实 VexRiscv 执行生产编译的内核，测试仅观察 MMIO 结果与周期。宽 4864 的完整内核周期包含两遍输入检查、exp/回退、sigmoid、乘法与结果检查；输出记录与后续量化在计时之外。单独的转换、exp、除法、乘法、检查与访存循环为诊断消融，不能相加冒充完整路径成本。模型装载、真实 DDR/native 链路、其他算子的 cache 干扰、整网 TTFT/decode 和板测留给下游；不得从局部加速倍数直接生成整网预测。
