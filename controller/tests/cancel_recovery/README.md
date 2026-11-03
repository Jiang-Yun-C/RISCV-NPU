# 取消后的服务恢复回归

这组测试检查同一次 `main()`、同一次模型装载中的“取消或超时 → 安全恢复 → 下一条真实请求到 EOS/READY”。零 LED 写入本身不足以判定恢复成功。

## 重复运行

需要 64 位 Linux、GCC 和 Python 3；不需要串口、FPGA 或生产模型文件。在包内 `code/controller` 目录运行：

```sh
python tests/cancel_recovery/run_validation.py --out /tmp/nexusrv-cancel-recovery
```

脚本编译增强版、四灯版、默认关闭增强功能的版本，以及独立 CE64 驱动门测试。结果写入指定目录的 `RESULT.json`，包括编译参数、二进制与源码摘要、逐例 UART/命令/状态路径、下一请求的真实 session/METRICS、写次数、READY 顺序和模型装载次数。顶层 `passed` 只有全部检查通过且所列源码在运行前后未改变时才为 `true`。`--skip-ce64` 仅供开发；使用时顶层不会报全通过。

既有生产流式回归可另外运行：

```sh
python -m unittest tests.production_streaming.test_native tests.production_streaming.test_enhancements
```

## 复现未修改 v3 的旧漏洞

`--baseline` 必须指向解压后的、未修改的 v3 包根目录，包含 `code/controller`；脚本只读取该目录：

```sh
python tests/cancel_recovery/reproduce_v3.py \
  --baseline /path/to/industrial-controller-chat-demo-20261101-v3 \
  --out /tmp/nexusrv-cancel-recovery/baseline
```

旧取消测试明确要求出现 `D27 HALTED`，没有要求排队的下一请求执行，因此会在服务不可继续时仍 PASS。复现脚本保存旧测试 PASS、原始 UART 和严格恢复判据的 `FAIL_EXPECTED_REPRODUCED`。该状态表示旧缺陷成功复现，不表示新修复通过。

## 夹具与证据边界

- **服务层**：运行生产 `main.c`、runtime、tokenizer、stream 和真实的小尺寸 Transformer 前向。使用既有 `NX_OPT13_TEST` 几何与合成权重/分词器；指定模式只覆盖返回的 next-ID，使 JSON/EOS 提交门可重复验证。UART、时钟、LED MMIO 和栈保护观察是原生边界夹具。它验证控制流程，不验证生产模型语义、板端速度或物理亮灭。
- **连续性**：同一进程、一次 main 入口、一次模型装载；覆盖 prefill/decode/已发 END 后的取消、stream0、重复与过期取消、半行取消跨 EOS/READY 或 timeout、取消后下一 text/action、以及相邻超时边界。故障、栈保护、模型失效和恢复回调失败必须保持停机且不能发布可恢复终态。
- **CE64 门**：调用生产 `nx_ce64_idle_safe()`、`nx_ce64_reset_session()` 和输入缓存失效逻辑；仅用受控 MMIO 响应模拟寄存器与异步 epoch/drain 进展，覆盖 owner、未释放 ACK、未完成事务、bridge、隔离和恢复失败。没有运行 CE64 RTL、DDR 训练或数值加速器。该层与 CPU 原生服务层分别记录，不能合称全板验证。
- `REQUEST_END.next_session` 是恢复后的空闲 session；下一次模型 begin 还会推进 session。测试同时记录两者，不把它们混为一个身份。

`uart/*.uart.txt` 是上述原生生产 C 的实际输出，可交给主机解析器做跨层测试；它们必须保留合成夹具来源标签。
