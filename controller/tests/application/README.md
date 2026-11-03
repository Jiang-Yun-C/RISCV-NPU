# T02 应用样例与评分

当前发布为 [应用 v2](../../docs/spec/application-v2-contract.md)：`v2/` 下 2048/50/200 条训练/开发/保留数据、独立标签和严格程序评分，结果见 [v2 验收报告](../../docs/reports/model-fp-baseline-v2.md)。`make t02-dev` / `make t02` 已指向冻结的适配模型；`make t02-test` 同时运行两版回归。

## 原版数据与评分（历史基线）

`dev.jsonl` 为 50 条开发样例（40 合法、10 非法），`heldout.jsonl` 为 200 条保留样例（160 合法、40 非法）。两者在第一次推理前由 `build_dataset.py` 一次性生成并写入 `dataset-lock.json`；生成器拒绝覆盖已冻结数据。分别包含 45/130 个不同指令文本和 50/200 个不同完整输入，不把模板变体声称为独立用户抽样。

`expected` 是人工制定的规范化答案，包含 actions/readings/error；它不进入当前待测请求的 prompt。开发集选出的少量示例可以进入固定对话提示，记录于 `configs/t02-demonstrations.json`。开发成绩包含这些已展示样例，不代表泛化效果。保留集指令及措辞族与开发集不交叉。

最终响应协议与范围见 [应用合同](../../docs/spec/application-contract.md)。`score.py` 仅解析完整命令数组或唯一的末行 `RESULT=`，检查 schema、参数边界、完整动作顺序、查询字段/读数、整体拒绝及 EOS；不修补模型输出。说明写对、实际命令写错仍算失败。原始拒绝能力与 checker 对非法输出的拦截不是同一指标。

类别及合法/非法分母分别汇总。`pair_id` 连接相同指令、不同状态、不同应执行动作的两条用例；两条均正确才算一组成对测试通过。任何输入、评分或模型更新都应建立新版本；不得覆盖冻结保留集或根据保留集失败调参。

```bash
make t02-test           # 无模型/GPU的评分器和数据合同回归
make t02-fetch          # 下载/核对固定模型 revision；唯一需要网络的入口
make t02-v1-dev         # 原版固定开发配置，全模型 FP32；逐次保存证据
make t02-v1             # 原版固定保留集，全模型 FP32；逐次保存证据
```

推理入口需要本工程锁定的 Python 环境、CUDA GPU、Linux `unshare --user --map-root-user --net` 支持。模型/tokenizer 只从本地加载，操作系统隔离网络并加 Python socket 审计。失败也保留全部逐条结果；当质量目标未满足时脚本返回 1，make 通常返回 2，不得把非零返回改写为 PASS。

每次结果保存完整 messages/prompt、输入/输出 token ID 与计数、原始输出、EOS/长度上限停止原因和逐条评分；另在全新进程中离线加载并重跑七条固定用例，核对输入与输出 token 序列。开发集质量门槛为合法 ≥90%、拒绝 ≥95%，冻结后对保留集使用相同门槛。最终结论见 [模型基线报告](../../docs/reports/model-fp-baseline.md)。
