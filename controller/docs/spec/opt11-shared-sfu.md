# OPT11 共享 SwiGLU 与 group64 块合同 v1

隔离覆盖层 `variants/opt11` 从已验收 OPT10 B＋OPT08 创建；根 A 和原冻结证据保留。生产软件回退默认开启，`nx_opt11_configure(context,1)` 在 idle 时显式选择硬件，0 恢复原 `nx_swiglu`＋OPT08 的 packed CE64 软件量化器（含板级 SRAM 组暂存，尾 K 使用原 T05 软件量化），非法配置不改变选择。软件路径需要 `fp32` 工作区。两条路径使用相同 RV32IMF/ILP32F、O2、非 fast-math、禁 FMA 收缩。

## 块命令和视图

保留 CE64 128 字节 descriptor、shadow 完整位图、epoch/generation、双 completion bank、ACK/owner、guard 与 native drain 协议。新私有 opcode=3；body 的 ABI/size/session/sequence 与原线性 transport 相同。M=N=1，K=1…4864。source 是 gate，scales 是 up，aq/sa 是输出，destination 是可选 FP32 诊断输出；output_stride=0 为 SwiGLU＋量化，1 为输入 FP32 的独立量化模式。其余字段必须为零。

输入是连续 K 个 FP32；Aq 分配 `ceil(K/64)*64` 字节，Sa 分配 `ceil(K/64)*4` 字节，FP32 诊断区为 K*4 字节。所有起点 16 字节对齐，分别位于 AC 或 BA 共享可写窗口，范围不得重叠，不接受缓存别名。输出不会预载 golden。K65 是 SFU/私有块接口能力；现有公共 CE64 linear/down 仍只接受 K896/K4864。

CPU 每段提交一次 descriptor，不逐元素 MMIO。硬件按 group64 通过原 DMA 读取 gate/up；最多 32 个 4 字节 beat，并按 4KiB 切分，尾组只读有效元素。成功后返回版本 1 的只读 `nx_opt11_view`，绑定 epoch、session、sequence、K、Aq/Sa 地址。调用者在视图有效期间不得写这些 buffer；任何其他命令、reset、epoch 改变或消费均使旧视图失效。`nx_opt11_down` 验证身份后把相同 Aq/Sa 地址交给真实 CE64 transport，不经过 CPU 重新量化或复制。模型装载器继续负责 Wq/Sw/bias 的不可变 seal；该私有接口不扩大公共 provider 能力。

## 算术和银行

2/4 lane 只改变组缓冲装入宽度及银行数。一个共享 exp、一个共享 restoring FP32 divider、一个共享 FP32 add/multiply 流水处理所有元素，没有复制每 lane 的 SFU。gate/up 分别按 `element%LANES` 选择物理同步单端口 bank，地址是 `element/LANES`；装入与运算读取互斥。FP32 候选和量化结果留在组私有缓冲。已有 64KiB CE scratch 仍为一个 128 位物理端口，DMA 与控制器互斥。

exp 先以 Q96 ln2 常数反复减法缩减，再用 21 阶 Horner 计算 `exp(-r)`。共享 radix-256 乘法每次用 13 个串行步骤；最后按缩减的 2 次幂生成 RNE binary32，保留次正规输出。常数来自高精度数学值，不依赖模型数据。缩减后的结果位于 [1/2,1]，leading-bit 判定、尾数/guard/sticky 和末次舍入分阶段寄存。它是新的数学实现，不能沿用被否决的 expf/LUT 候选资格；数值由独立 binary64 exp 和累计 T05 检查重新验收，不声称已穷举所有 FP32 指数输入。

divider 每周期生成一个商位，27 位商加余数 sticky，单独处理规格化/次正规和 ties-even。add/multiply 复用 CE64 的 RNE FP32 流水，不合并两次乘法。调度器逐次等待结果，流水本身的 II 不等于完整 SwiGLU II。保持 `gate>=0` 的稳定 sigmoid 分支、`(gate*sigmoid)*up` 的两次独立 FP32 乘法及负零。

全组先检查 gate/up 有限性，计算候选并归约 amax，随后 scale=`amax/127`；非零组至少为最小 normal，零组 scale 为 +0。对相同 FP32 输入，使用 FP32 除法、round-even、[-127,127] 截断的 Aq 和 Sa 必须逐位一致。尾元素内部补零，但 FP32 诊断只写有效 K。K 上界保证每命令读取最多 38912 字节、写入最多 24624 字节，内部 payload 累计可用 16 位，外部 completion 仍零扩展为原 64 位 ABI。

## 错误、发布与周期

所有输入及结果合法后才允许组写回。NaN/Inf 或输出溢出不提交当前组。较早完成的组可能已经写入；整段失败时不发有效视图，不得消费部分段。stop/timeout/reset 可取消私有算术，但已由 DMA 接受的请求及 AXI offers 必须完成排空。原 native 写后 1024 周期等待保留，completion/ACK/owner 释放在真实可见性之后。软件把硬件一般失败映射为原 transport 的 EFAULT，bus error 为 EIO，数值失败为 ENUMERIC；reset 后重新建 session/view。

组间串行，不建立 DMA/算术或跨组重叠模型，不使用 `max(compute,transfer)`。分别保存读取、计算/量化、写回、其他周期和真实 CPU API 周期；FP32 诊断写回与后续 down 单列。性能对照使用相同的实际板级 ROM/SRAM RTL 栈（0x28000…0x30000），gate/up/输出/权重走真实数字 native DDR。早期 DDR 栈探索的超时不用于软件/融合速度比；该变化不能算成 SFU 收益。

## 资格边界

真实 CPU/VCS/cocotb＋独立 native 数字存储模型负责本卡协议、组数值和代表 down 接续。完整 T05 累计及质量运行使用经 RTL fixtures 对照的 Q96 C 数据通路模型，不冒充整网 RTL 执行。PDS 使用本次 2024.2/build178169 PASS 收据、固定 seed=2、125MHz 约束；控制器＋组的 OOC 综合与组组件的 OOC route 分开报告。保留的 DMA/scratch、dispatch mux、完整 SoC 资源和时序/CDC/RDC 交 OPT16；实板交 OPT17。本卡不执行 JTAG/UART 板控、SD 写入或烧录。
