# CE64 有序恢复实验

新模块 `rtl/ce64/nx_ce64_fp32_ordered.sv` 将独立 p/v 预计算与依赖 accumulator 的 add 分开。每次 add 使用上一次实际硬件返回的 partial，按请求顺序退休；最多四个准备上下文，一个 add 在途，最后 group 返回前不接收下一 row。旧 F32-S/P、原 E0 脚本与收据保持原字节。

首组核延迟 18 周期，同一 row 的后续 group 实测间隔 6 周期。核的 ≤16 单组延迟门禁仍 OPEN；6 周期间隔没有代替延迟签核。弹性输入/输出边界另加两周期。RTL 每轮 31554 个 group，独立 CSV 比较 220878 个字段；含原 E0 的 7894 个冻结 T16 group（493 个输出的算术子集），另有数值/协议错误、长反压和 local reset/epoch。没有运行 CE 固件或原 T16 控制矩阵，也没有 DMA、偏置或板级资格。

v1 的重复 FIRST 错误会重置 accumulator，原始 FAIL 保留。v2 修复；v3 再限定四个上下文。映射 v1 的 idle monitor 被输出寄存器当作 payload 取样；v2 改为真实控制状态并计 ingress/egress。它们均不是最终集成版本，资格必须绑定具体父收据。

用新 run_id 复跑：

```sh
npu-python scripts/run_ce64_ordered.py --run-id ordered-new-rtl
npu-python scripts/run_ce64_ordered.py --stage map --run-id ordered-new-map \
  --tool-evidence evidence/PDS_TOOLCHAIN/ce64-s0-tool-20261013-v1 \
  --rtl-receipt evidence/CE64_ORDERED/ordered-new-rtl
npu-python scripts/run_ce64_ordered_mapped.py --run-id ordered-new-mapped \
  --parent evidence/CE64_ORDERED_MAP/ordered-new-map \
  --rtl-receipt evidence/CE64_ORDERED/ordered-new-rtl
```

本模块 reset_n 仅为算术局部复位。产品 soft reset 必须经另行实现/验证的 drain coordinator；这里的 reset 用例不转授给 AXI/native adapter。
