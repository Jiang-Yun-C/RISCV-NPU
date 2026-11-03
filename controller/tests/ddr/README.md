# T23 独立 DDR 验证

`make t23`：三个总线宽度 × seed 1/7/19，128 位 seed1 复跑，四个原始 FAIL 负例。实际 VCS 执行 RTL；cocotb 独立字节模型支持延迟提交、随机请求/返回间隙和故障注入，VCD 再独立重建双方事务。

T04 的 141 次写/148 次读来自冻结 fixture。`t14-boundaries.json` 保存冻结 T14 的第 129 行、超暂存行、4099 字节尾部和高地址输入，逐项保存原文件/父 golden hash；只覆盖传输边界，Coral 数值没有在本组件重复执行。

`make t23-native`：校验并恢复 T22 保存的原生 HMIC1.10 保护控制器源码，在新目录从源码编译适配器和 4KiB DFI 内存模型。覆盖 256 拍 AXI、16+1 native 拆分、32 个字节掩码、独立读回与 ID。PHY 已替换，模型 init_done 不计真实校准。

`make t23-test`：有效 payload/64 位计数、32 位边界、丢采样/复位/错误/短窗及实际时钟窗口的拒绝逻辑。测试生成数据不能用于实测带宽声明。物理带宽 receipt 的 samples 必须包含连续 sequence、host_elapsed_s、core_cycles、有效 write_payload_bytes/read_payload_bytes、errors、init_done，至少 10 秒；counter 为已展开的 64 位值。原始捕获、代码/位流身份和真实目标由正式门禁另外检查。

合同见 [ddr-t23-adapter.md](../../docs/spec/ddr-t23-adapter.md)。当前板测暂缓记录继续有效。

`make t23-netlist ARGS="--synthesis evidence/T23_SYNTH/<run-id>"` 用实际 ADS 网表与同版原语重跑 native 控制器读写/掩码检查。PDS 默认1024周期等待不作模型缩短。
