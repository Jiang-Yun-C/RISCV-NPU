# 可复用外存模型

接口、加载命令、错误/复位语义及限制见 [T04 合同](../../docs/spec/memory-t04-contract.md)。

- `sparse_memory_pkg.sv`：4KiB 分页 byte 存储、批量 BIN 与稀疏 BSS 装载。
- `axi_sparse_mem.sv`：独立五通道、可反压、固定种子延迟和错误注入的 AXI 行为从端。
- `prepare_image.py`：先验证 ELF/BIN，再生成内部 load.plan 和带哈希的 image.json。
- `test_images.py`：有效加载和畸形镜像/模式的桌面回归，`make t04-test`。

未经检查的 ELF 不直接交给 SV 模型。输出路径不能含空白；不覆盖已有装载输出目录。

T07 已追加 128-bit/ID6 验收；`TIMING_CONTROL=1` 可按 plusarg 设置响应延迟、数据服务间隔和地址接收时隙。默认值保留 T04 时序，旧 32/64 位全验收已重跑。模型上限和测量边界见 [T07 合同](../../docs/spec/backend-t07-probe.md)，这些参数不模拟真实 DDR bank/row 或刷新。
