# T06 Coral 执行探针

从工程根目录运行 `make t06`。配置、证据与适用边界见 [T06 合同](../../docs/spec/coral-t06-contract.md)。

- `audit_source.py`：以 AST 读取锁定源码中 scalar/RVV/VME target 的实际 flags，输出源文件 hash。
- `tb_coral.sv`：AXI 从口装载/回读、入口设置、启动、halt/fault、DTCM dump、逐拍 CSV/VCD；外部主口访问会失败。
- `prepare.py`：复用 T04 ELF 校验，加上 TCM 分区与符号检查，生成确定性输入和独立期望值。
- `vector_probe.c`、`start.S`、`link.ld`：67 元素有符号加宽加法/乘法/规约，8KiB ITCM 与 32KiB DTCM。
- `check.py`：独立检查所有计算输出、保护区、必需计算指令、AXI 装载/响应/回读/稳定性及完成状态。

标量对照跑上游浮点示例，RVV target 跑同一浮点示例、上游 RVV 示例和自定义程序。上游源码保持干净。复跑可以使用 Bazel 缓存；VCS 每次独立编译。`evidence/T06_NEGATIVE/` 的预期失败记录应保留 FAIL 状态。
