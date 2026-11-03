# Coral RTL 静态验证修复

锁定的 Coral ZIP 保留原始身份。T06/T07/T14/T15/T16（含 T19）解包到本次 build 后，统一由 `scripts/coral_rtl.py` 检查补丁前后 SHA256、应用补丁并归档修改后的文件。新上游或重复应用必须报错，不能模糊匹配后静默继续。SpyGlass 消费与 VCS 相同的修复后目录。

- `fpnew_fma_multi.sv`：`sum_sticky_bits` 是 `[2*PRECISION_BITS+2:0]`，流水寄存器误写为 `[3*SUPER_EXP_BITS+4:0]`。FP32 下将 51 位截成 29 位，后续访问第 50 位越界；寄存器修正为与输入相同宽度，保留舍入后下溢判断所需 sticky 位。
- `fpnew_opgroup_multifmt_slice.sv`：只有 DIVSQRT 操作组具有 divider 的 ready/done 驱动。同步归约增加 `OpGroup == DIVSQRT` 条件，其他操作组保持既有 unused 分支常量，避免读取未驱动线。
- `fpnew_cast_multi.sv`：保留有符号 exponent 比较和 fraction 位段修复。
- `fpnew_fma.sv`、`fpnew_fma_multi.sv`：明确保留的归一化位段与多格式 fraction 对齐，保留实际隐含位和 sticky 消费关系。
- `rvv_backend_decode_unit_ari_de2.sv`、`rvv_backend_pmtrdt_unit_permutation.sv`：保留已验证的等宽索引 cast。
- `multi_fifo.sv`：用同宽 prefix sum 表达 push/pop 计数；CHAOS_PUSH 用互斥 `if/else` 接收标志及显式压紧链表达原 lane 顺序。未知 push 仍按原 procedural-if 忽略，计数中的未知位仍传播，不修改 clear/reset、FULL_PUSH 或内存更新优先级。
- `rvv_backend_dispatch_structure_hazard.sv`：DISPATCH3 每个读端口只赋值一次，选择函数保留原 case 分支和回退来源；结构冒险另行选择。DISPATCH2 保持原代码。
- `RvvFrontEnd.sv`：配置有效性使用等价的位归约；trap 选择函数保留最低有效 lane 优先级及无有效 lane 时的默认数据。

manifest 当前覆盖 9 个文件。原始 ZIP、旧 receipt 与历史失败保留；没有 waiver、黑盒或必要接口删除。每个文件继续保留其原许可证。功能与静态复验见 R01 任务卡和报告；告警减少不等于设计验收通过。
