# OPT12 共享向量块合同 v1

隔离覆盖 `variants/opt12` 叠加 OPT11 v8 的 B 候选；根 A、OPT01–11 的收据和板上身份不修改。使用同一 exp、FP32 add/multiply、divider、2 lane 输入 bank、group64 队列与原 DMA/scratch；新增单个整数 restoring sqrt。FP32 结果改为单端口同步 RAM，窥读延迟一拍；新增 128 个 FP32 组根存储（两银行），不复制每算子计算单元。

私有 opcode=3，128 字节 descriptor 和原 completion、shadow、epoch/generation、ACK/owner、native drain 保持。d24 模式 0 SwiGLU、1量化、2 add/残差、3 mul、4 scale、5 sum、6 max、7 RMSNorm。d25=0/1 选择额外 group64 量化（0/1 模式总是量化）；d26 仅 scale 模式保存有限 FP32 标量，其余为零。d18 输入、d20 第二输入/gamma（仅模式0/2/3/7非零）、d19 可选 FP32 输出、d22/23 可选 Aq/Sa。K=1…4864；sum/max 输出一个 FP32，禁止量化；其余输出 K 个 FP32，量化时可省 FP32 写回。Aq 补到64，Sa 每组一个FP32。全部起点16字节对齐，限定 AC/BA 共享窗口，不接受缓存别名。未使用的地址字段必须为零。

add/mul/scale/RMSNorm 允许 FP32 输出与任一输入完全同址；部分重叠拒绝。Aq/Sa 与任何输入/输出不重叠，两个输入保持独立。先完整读取当前组再写回，因此精确别名不会破坏后续输入。输入在调用期间由调用者保持不可变；有效输出 view 绑定 epoch/session/sequence，下一命令/reset/消费使其失效。仅整段成功并完成 drain/ACK/owner release 后发布 view；失败不发布，已写组和原地输入视为失效，不能消费或重试为原输入。这是发布原子性，不承诺内存回滚。

RMSNorm 第一遍只读 x，将独立舍入的 x² 以相邻配对树归约；每64组内补零，全向量右补到下一2次幂。组根继续经过同一浮点单元归约，不改变 T05 配对顺序。其后依次 FP32 sum/K、加1e-6、sqrt、1/sqrt，第二遍重新读 x 与 gamma，计算两次独立乘法 `(x*inv)*gamma`。sqrt 用24次 radix-4 整数开方和精确余数舍入，保留次正规输入。归约溢出、非有限输入/输出报 ENUMERIC。max 的内部 padding 为负无穷，外部非有限仍拒绝；零的相等比较选择正零。

基本模式先产生 FP32；只有显式选择量化才执行 group64 的 amax/scale/RNE 饱和，残差不提前量化。RMSNorm→Aq/Sa 可共驻留64个 FP32 组结果，无CPU再遍历，量化 view 直接通过原 `nx_opt11_down` 消费。RMSNorm 额外读取一次 x；有效 payload 为12K字节（x两次、gamma一次），额外片上组根512字节，组缓冲复用。所有 pass/组/DMA 串行，无未经验证的重叠。

`nx_opt12_configure(context,1)` 在 idle 显式选择硬件，默认0走软件（整64倍数复用OPT08原packed量化，尾组走T05原函数）；拒绝配置不改变开关。新API输出未发布前不可消费，`nx_opt12_acquire` 检查有效性与代次。原 `nx_opt11_run/down` 仍可用。数值/总线/stop/timeout/reset 错误均保留原状态与恢复协议，accepted DMA 必须排空。代表 SoC 验证使用实际板级64KiB SRAM，双方相同56KiB栈区域（0x22000…0x30000，留8KiB），text/globals/tensors走native DDR。

独立入口 `make opt12` / `opt12-component` / `opt12-numeric` / `opt12-quality` / `opt12-ooc` / `opt12-accept`。运行前冻结seed1/7/19/1-repeat、150M周期、7200秒外层上限；组件另有250M周期硬件期限。非空XML、live检查、fixture/source/tool/VPI hash及代表波形均为必需。累计/质量用经RTL对照的C数据通路模型，区别于整网RTL执行；未修改T05阈值。

OOC采用PDS2024.2/build178169、PG2L200H/FBB676/-6、8ns、固定seed2及本次工具PASS收据。块控制器＋共享组的综合与组件内部route分别报告；整SoC、dispatch、CDC/RDC、板速交OPT16/17。attention/RoPE/softmax硬件不在首版范围，长上下文用独立CPU测量与工作量估算决定后续交接。未执行JTAG/UART板控、SD写入或烧录。
