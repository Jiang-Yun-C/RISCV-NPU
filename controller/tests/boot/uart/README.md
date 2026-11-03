# T17 UART 协议启动验证

`make t17` 重新生成 T09 Cache 开启 CPU、编译 Boot ROM 和两幅 2,160B 应用，
在真实 UART 引脚传输固定 fixtures，运行全部错误/恢复/重装及 PRELOAD 用例。
`make t17-smoke` 只作首次连通；`make t17-test` 跑桌面协议、C/主机 CRC/地址规则和主机重试回归。

`generate_fixtures.py` 生成串口输入及独立 golden；固定版本位于
[uart_boot](../../cocotb/fixtures/uart_boot/manifest.json)，重建须逐字节一致。
`scoreboard.py` 从 CSV 独立重构 AXI，核对目标写事务、错误无跳转和当前镜像指令。
`waveform.py` 解码完整 UART VCD，与 cocotb 引脚 monitor 的值和时间戳交叉核对。
Boot ROM/SRAM 与应用隔离；PROTOCOL_BOOT 的目标应用 64KiB 初态须全部为零。

每次构建与运行均使用新目录，保留源码快照、工具身份、case config、XML、检查计数、
UART trace、AXI/退休 CSV、初始/最终 RAM、VCD。归档复验会重新评分原始数据。
合同见 [uart-boot-v1](../../../docs/spec/uart-boot-v1.md)。
