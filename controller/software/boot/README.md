# UART 主机下载工具

`download_uart.py` 使用 [NXU1 合同](../../docs/spec/uart-boot-v1.md) 下载连续 raw RV32 镜像。
传输前检查可写窗口、尺寸和入口；每包校验 ACK CRC，DATA ACK 丢失时重发并接收 DUP。
RUN ACK 丢失时报告执行状态未确认，避免自动重复跳转。

```bash
npu-python software/boot/download_uart.py application.bin --port /dev/ttyUSB0 --baud 115200
```

`--address` / `--entry` 默认 `0xb4000000`；`--timeout` 默认为 2 秒，`--retries` 默认为 3。
需要外部平台已运行相同 Boot ROM。当前实板 UART 时钟/波特率尚未验收。
测试入口：`make t17`（真实 VCS）与 `make t17-test`（桌面协议/主机重试）。
