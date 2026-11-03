# SoC 外存边界

`soc_memory_env.sv` 将共享 `axi4_if` 接到仿真内存，已被 `tb_axi` 实际实例化。
未来 `tb_soc` 在 `soc_core.ext_mem` 接此环境，`fpga_top` 在同一端口接 T23 的真实 DDR 适配器。
core 中禁止包含行为内存、预加载、随机延迟或厂商 DDR IP。

T03 的 `t03_soc` 仍使用简单 I/D 临时 RAM；本目录没有声称存在已完成的 `soc_core` 或 `fpga_top`。
core 重构和桥接在后续集成任务中验收。端口、reset、PRELOAD/PROTOCOL_BOOT、初始化和
下游职责见 [T04 合同](../../docs/spec/memory-t04-contract.md)。

T16 的真实 CPU/Coral 共享总线闭环回归已交付在 [tests/soc_accel](../soc_accel/README.md)，使用本项目的行为外存；验收方式为 VCS + PRELOAD。入口 `make t16`，日常短回归 `make t16-regression`，证据见 [T16 报告](../../docs/reports/T16.md)。
