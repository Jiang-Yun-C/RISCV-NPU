# T07 真实 Coral 外存算子探针

`make t07` 新建构建和证据目录，重新编译 T06 归档的 RVV RTL、执行 128-bit/ID6 协议测试、123 组算子/诊断案例、五个损坏证据负例及 T04/项目回归。默认并发 24 个独立 VCS 进程；并发仅缩短主机验收时间，报告的硬件周期按各块窗口累计。`make t07-probe` 只运行单 token K 投影及接口测试，不关闭完整 T07。

| 文件 | 职责 |
|---|---|
| linear.c | RVV 分组点积、标量 FP32 恢复，外存权重及结果 |
| prepare.py | 验证 T05 文件身份，生成有界 ELF/TCM 镜像与外存块 |
| tb_external.sv | 从口装载、主口外存、稳定性/属性检查、计数和有限波形 |
| check.py | 逐事务核对读数据、从写事务重建 dot/Y、检查数值及原始计数 |

复检保存结果：

```bash
npu-python scripts/verify_t07_handoff.py evidence/T07/<run-id>
```

该入口核对全部归档 hash、T05 原始向量来源与实际 oracle 切片，重跑每组检查器，将 3,000 周期波形窗口与事件记录对应，并核对时序上限、完整输出行覆盖及负例。独立汇总也可使用 `scripts/summarize_t07.py <run-dir> <new-output-dir>`。

T05/T06 输入目录由 [配置](../../configs/t07-external.json) 固定。编译器使用 T06 锁定缓存；清理缓存或迁移主机时先复建并验收前置任务。无 PDS、厂商 DDR IP 或板卡依赖。当前程序接受预量化 Aq/Sa，只验 M=1/4 和本文记录的形状；这不是 T08/T15 的通用生产 API。

数值与性能覆盖、head 代表块、诊断写入开销和未验证项见 [报告](../../docs/reports/backend-sim-feasibility.md) 与 [合同](../../docs/spec/backend-t07-probe.md)。
