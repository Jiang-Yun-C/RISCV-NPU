# CE64 E0 算术与资源试验

本目录对应 Pro 执行包的第一次小闭环。`rtl/ce64/` 是新的算术候选；现有 Coral/SoC/驱动和冻结数据未替换。完整资格记录与判断见 `docs/reports/ce64-review-1/E0_DECISION.md`。

- D16-S / D16-P：相同 16 路 signed int8 乘法，比较直接归约和乘积寄存流水。
- F32-S：一个 MUL 复用两次、一个 ADD，保存每一步 binary32 舍入结果。
- F32-P：两级独立 MUL 和一个 ADD，按输入次序返回；acc 是请求提供的快照。多次更新同一输出时必须等前次 partial，或另建经过验证的 accumulator 调度。
- 私有 `nx_ce64_fma_retimed.sv` 增加两个弹性寄存阶段；源自冻结 fpnew 原语，原件与来源 hash 在 vendor/ 和 retiming-origin.json。仅固定 FP32/RNE/MUL/ADD、外部 register override 为零的实例被测试。

精确 oracle 使用整数乘二的幂，逐步 round-to-nearest ties-to-even，并与 numpy 的独立 FP32 运算交叉检查。T16 实际 fixture、golden、阈值、模型 payload 和 expected npz 的身份运行前核对。合成边界用例独立于正式 golden。

恢复检查比较 p/v/partial、私有错误码和 IEEE flags；覆盖零/负零、合法运算产生的 subnormal、underflow/overflow、非法 scale、NaN/Inf、错误优先级、反压和局部 reset/epoch。group 测试还覆盖 -128、zero scale 配非零 q、mask、K65/K127 实际反馈链及冻结 M1/M4/M8、N129、K4864 数据。DMA、Aq padding 全调用验证、偏置硬件、全局故障顺序和整次调用发布属于后续阶段。

复跑命令应使用新的 run-id，已有证据目录不可覆盖：

```sh
make pds2024-check ARGS='--run-id ce64-new-tool-check --synthesize'
npu-python scripts/run_ce64_e0.py --stage rtl --run-id ce64-new-rtl
npu-python scripts/run_ce64_e0.py --stage map --profile F32-S \
  --tool-evidence evidence/PDS_TOOLCHAIN/ce64-new-tool-check --run-id ce64-new-f32s
npu-python scripts/run_ce64_mapped.py --parent evidence/CE64_E0_MAP/ce64-new-f32s \
  --rtl-receipt evidence/CE64_E0_RTL/ce64-new-rtl --run-id ce64-new-mapped
npu-python scripts/run_ce64_restore_cpu.py --run-id ce64-new-cpu
npu-python scripts/run_ce64_formal.py --run-id ce64-new-formal
npu-python scripts/verify_ce64_e0.py --parent evidence/CE64_E0_RTL/ce64-new-rtl --run-id ce64-new-verify
```

`--profile` 可取 D16-S、D16-P、F32-S、F32-P。PDS 使用每变体相同的弹性输入、输出寄存边界及 8ns 时钟；统计所有可消费端口，不关闭错误或 tag 逻辑。综合估计与实际布线路径分别登记。

组件面积通过后，`scripts/run_ce64_route.py --parent <map receipt> --run-id <new id>` 可做组件实现。恢复探针 371 个端口使用自动 IO 分配，仅用于组件内部时钟路径，不是实板引脚/复位/CDC 合同，不生成可下载的板级镜像。无 IO 插入的 mapped 逻辑直接 dev_map 会触发 DRC，失败原件保留。

形式收据只证明 direct-dot 的八步二态控制属性，并用错误 tag 断言取得反例；不声称无界活性或浮点形式证明。实际负例同时检查 Fatal/PASS 标记，因为此 VCS 配置在 `$fatal` 后可能退出 0。
