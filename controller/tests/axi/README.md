# AXI 环境验收

`make t04` 从新目录编译并运行 32/64 位测试，结果在 `evidence/T04/<run-id>/`。
`make_workload.py` 生成 AW/W/AR 向量和独立字节参考；`tb_axi.sv` 是独立五通道 BFM，
主端 B/R 也施加反压；`check_axi.py` 比较全部握手和 VCD，确认完整完成、ID/顺序、稳定性及覆盖。
`tb_reset.sv` 另验稀疏清零、带未完成事务的复位和错误注入后恢复。

复验保留证据时，将案例路径与对应 `stimulus-*/workload.json` 传给检查器：

```bash
npu-python tests/axi/check_axi.py evidence/T04/RUN/artifacts/case-CASE \
  evidence/T04/RUN/artifacts/stimulus-STIMULUS/workload.json
```

默认必须有 CSV、VCD 和 simulation.json；`--no-waveform` 仅供损坏 CSV 的负例隔离使用。
不是已接入 CPU 的 SoC 验收，也不用于宣称 DDR/板端带宽。完整接口见 [合同](../../docs/spec/memory-t04-contract.md)。

`make t07` 还以 `AXI_DATA_W=128`、`AXI_ID_W=6` 运行本 BFM；生成器使用 `--width 128 --id-bits 6`，覆盖 0–63 的 ID，并保留 seed 1/7 的协议与波形检查。Coral 的实际单拍访存在独立的 [外存探针](../coral_external/README.md) 验收。
